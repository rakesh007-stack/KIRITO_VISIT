import asyncio
import json
import aiohttp
from flask import Flask, jsonify
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info

# Try to use uvloop for faster event loop execution (Optional)
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

app = Flask(__name__)

# --- Helper Functions ---

def load_tokens(server_name):
    """Tokens load karne ka logic"""
    paths = {
        "IND": "token_ind.json",
        "BR": "token_br.json", "US": "token_br.json", 
        "SAC": "token_br.json", "NA": "token_br.json"
    }
    path = paths.get(server_name, "token_bd.json")
    
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return [item["token"] for item in data if item.get("token") not in ["", "N/A", None]]
    except Exception as e:
        print(f"❌ Error loading tokens: {e}")
        return []

def get_url(server_name):
    """Server ke basis pe URL return karega"""
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    return "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

def parse_protobuf_response(response_data):
    """Protobuf binary data ko JSON format me convert karne ke liye"""
    try:
        info = Info()
        info.ParseFromString(response_data)
        return {
            "uid": info.AccountInfo.UID or 0,
            "nickname": info.AccountInfo.PlayerNickname or "",
            "likes": info.AccountInfo.Likes or 0,
            "region": info.AccountInfo.PlayerRegion or "",
            "level": info.AccountInfo.Levels or 0
        }
    except Exception as e:
        print(f"❌ Protobuf parse error: {e}")
        return None

# --- Core Async Logic ---

async def visit(session, url, token, data):
    """Single POST request with headers"""
    headers = {
        "ReleaseVersion": "OB53",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0],
        "Connection": "keep-alive"
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False, timeout=5) as resp:
            if resp.status == 200:
                body = await resp.read()
                return True, body
            return False, None
    except:
        return False, None

async def process_visits(tokens, uid, server_name, target=1000):
    """Main loop jo concurrent requests handle karega"""
    url = get_url(server_name)
    total_success = 0
    player_info = None
    
    # Encrypt data once
    encrypted_hex = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
    request_data = bytes.fromhex(encrypted_hex)

    # Optimization: TCPConnector with limit=0 for max speed
    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        token_count = len(tokens)
        
        while total_success < target:
            # Dynamic batching
            remaining = target - total_success
            batch_size = min(remaining, 500) # Fast processing limit
            
            tasks = []
            for i in range(batch_size):
                token = tokens[(total_success + i) % token_count]
                tasks.append(visit(session, url, token, request_data))
            
            results = await asyncio.gather(*tasks)
            
            for success, response in results:
                if success:
                    total_success += 1
                    if player_info is None and response:
                        player_info = parse_protobuf_response(response)

            print(f"Server: {server_name} | UID: {uid} | Progress: {total_success}/{target}")
            
            if total_success >= target:
                break
                
    return total_success, player_info

# --- Routes ---

@app.route('/<string:server>/<int:uid>', methods=['GET'])
def start_visits(server, uid):
    server = server.upper()
    tokens = load_tokens(server)
    
    if not tokens:
        return jsonify({"status": "error", "message": "No tokens found"}), 404

    # Run async function in background
    success_count, player_data = asyncio.run(process_visits(tokens, uid, server))

    if player_data:
        response = {
            "uid": player_data["uid"],
            "nickname": player_data["nickname"],
            "level": player_data["level"],
            "likes": player_data["likes"],
            "region": player_data["region"],
            "success": success_count,
            "target_reached": success_count >= 1000
        }
        return jsonify(response), 200
    
    return jsonify({"error": "Failed to fetch player info or process visits"}), 500

if __name__ == "__main__":
    # Flask ko threaded mode me run karna fast requests handle karne ke liye
    app.run(host="0.0.0.0", port=5100, debug=False, threaded=True)
