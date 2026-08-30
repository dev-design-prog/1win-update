from aiohttp import web
import json
import hmac
import hashlib
import urllib.parse
from database import Database

db = Database("/tmp/casino.db")
BOT_TOKEN = "1780309782:kovRk5ZPCxt_frYbc7wfq2Rg5GPfMJ3ObcG"


def verify_telegram_data(init_data: str) -> dict | None:
    """Verify Telegram WebApp init data"""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data))
        check_hash = parsed.pop("hash", "")
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(computed_hash, check_hash):
            user_data = json.loads(parsed.get("user", "{}"))
            return user_data
    except Exception:
        pass
    return None


def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Init-Data",
    }


async def handle_options(request):
    return web.Response(headers=cors_headers())


async def get_user(request):
    init_data = request.headers.get("X-Init-Data", "")
    user_data = verify_telegram_data(init_data) if init_data else None
    
    # For development, allow user_id from query
    if not user_data:
        user_id = request.rel_url.query.get("user_id")
        if user_id:
            user_data = {"id": int(user_id)}
    
    if not user_data:
        return web.json_response({"error": "Unauthorized"}, status=401, headers=cors_headers())
    
    user = db.get_user(user_data["id"])
    if not user:
        db.add_user(user_data["id"], user_data.get("username", ""), user_data.get("first_name", ""))
        user = db.get_user(user_data["id"])
    
    return web.json_response({
        "user_id": user["user_id"],
        "username": user["username"],
        "first_name": user["first_name"],
        "balance": user["balance"],
    }, headers=cors_headers())


async def play_slots(request):
    init_data = request.headers.get("X-Init-Data", "")
    user_data = verify_telegram_data(init_data) if init_data else None
    
    body = await request.json()
    if not user_data:
        user_id = body.get("user_id")
        if user_id:
            user_data = {"id": int(user_id)}
    
    if not user_data:
        return web.json_response({"error": "Unauthorized"}, status=401, headers=cors_headers())
    
    user_id = user_data["id"]
    bet = int(body.get("bet", 100))
    
    if bet < 100:
        return web.json_response({"error": "Min bet is 100"}, status=400, headers=cors_headers())
    
    if not db.deduct_balance(user_id, bet):
        return web.json_response({"error": "Insufficient balance"}, status=400, headers=cors_headers())
    
    import random
    symbols = ["🍋", "🍊", "🍇", "🍒", "⭐", "7️⃣"]
    win_chance = 0.008  # 0.8%
    
    is_win = random.random() < win_chance
    if is_win:
        result = ["7️⃣", "7️⃣", "7️⃣"]
        win_amount = bet * 10
        db.add_balance(user_id, win_amount)
        db.add_game_history(user_id, "slots", bet, "777", win_amount)
    else:
        result = []
        for _ in range(3):
            s = random.choice([s for s in symbols if s != "7️⃣"])
            result.append(s)
        while result == ["7️⃣", "7️⃣", "7️⃣"]:
            result = [random.choice([s for s in symbols if s != "7️⃣"]) for _ in range(3)]
        win_amount = 0
        db.add_game_history(user_id, "slots", bet, "".join(result), 0)
    
    new_balance = db.get_balance(user_id)
    return web.json_response({
        "result": result,
        "win": is_win,
        "win_amount": win_amount,
        "balance": new_balance,
    }, headers=cors_headers())


async def play_mines(request):
    init_data = request.headers.get("X-Init-Data", "")
    user_data = verify_telegram_data(init_data) if init_data else None
    
    body = await request.json()
    if not user_data:
        user_id = body.get("user_id")
        if user_id:
            user_data = {"id": int(user_id)}
    
    if not user_data:
        return web.json_response({"error": "Unauthorized"}, status=401, headers=cors_headers())
    
    user_id = user_data["id"]
    action = body.get("action")  # "start", "reveal", "cashout"
    
    if action == "start":
        bet = int(body.get("bet", 100))
        mines_count = int(body.get("mines", 3))
        
        if bet < 100 or bet > 500:
            return web.json_response({"error": "Bet must be 100-500"}, status=400, headers=cors_headers())
        if mines_count not in [3, 5, 8]:
            return web.json_response({"error": "Invalid mines count"}, status=400, headers=cors_headers())
        if not db.deduct_balance(user_id, bet):
            return web.json_response({"error": "Insufficient balance"}, status=400, headers=cors_headers())
        
        import random
        grid = [False] * 25
        trap_positions = [7, 8, 9, 11, 12, 13, 17, 18, 6, 3, 21, 4, 20]
        if random.random() < 0.6 and mines_count <= len(trap_positions):
            mine_positions = random.sample(trap_positions, mines_count)
        else:
            mine_positions = random.sample(range(25), mines_count)
        for pos in mine_positions:
            grid[pos] = True
        
        session = {
            "user_id": user_id,
            "bet": bet,
            "mines_count": mines_count,
            "grid": grid,
            "revealed": [],
            "multiplier": 1.0,
            "active": True,
        }
        game_sessions[user_id] = session
        
        return web.json_response({
            "status": "started",
            "bet": bet,
            "mines": mines_count,
            "balance": db.get_balance(user_id),
        }, headers=cors_headers())
    
    elif action == "reveal":
        cell = int(body.get("cell"))
        session = game_sessions.get(user_id)
        if not session or not session["active"]:
            return web.json_response({"error": "No active game"}, status=400, headers=cors_headers())
        
        if cell in session["revealed"]:
            return web.json_response({"error": "Already revealed"}, status=400, headers=cors_headers())
        
        session["revealed"].append(cell)
        is_mine = session["grid"][cell]
        
        if is_mine:
            session["active"] = False
            db.add_game_history(user_id, "mines", session["bet"], "lose", 0)
            del game_sessions[user_id]
            return web.json_response({
                "hit_mine": True,
                "mine_positions": [i for i, v in enumerate(session["grid"]) if v],
                "balance": db.get_balance(user_id),
            }, headers=cors_headers())
        else:
            safe_cells = 25 - session["mines_count"]
            revealed_safe = len(session["revealed"])
            multiplier = calculate_multiplier(session["mines_count"], revealed_safe)
            session["multiplier"] = multiplier
            
            return web.json_response({
                "hit_mine": False,
                "multiplier": multiplier,
                "revealed": session["revealed"],
                "balance": db.get_balance(user_id),
            }, headers=cors_headers())
    
    elif action == "cashout":
        session = game_sessions.get(user_id)
        if not session or not session["active"]:
            return web.json_response({"error": "No active game"}, status=400, headers=cors_headers())
        
        if not session["revealed"]:
            # Refund
            db.add_balance(user_id, session["bet"])
            del game_sessions[user_id]
            return web.json_response({"error": "No cells revealed"}, status=400, headers=cors_headers())
        
        win_amount = int(session["bet"] * session["multiplier"])
        db.add_balance(user_id, win_amount)
        db.add_game_history(user_id, "mines", session["bet"], f"win x{session['multiplier']:.2f}", win_amount)
        
        session["active"] = False
        del game_sessions[user_id]
        
        return web.json_response({
            "win_amount": win_amount,
            "multiplier": session["multiplier"],
            "balance": db.get_balance(user_id),
        }, headers=cors_headers())
    
    return web.json_response({"error": "Invalid action"}, status=400, headers=cors_headers())


def calculate_multiplier(mines: int, revealed: int) -> float:
    safe = 25 - mines
    mult = 1.0
    for i in range(revealed):
        mult *= (safe - i) / (25 - i)
    return round(1.0 / mult * 0.95, 2) if mult > 0 else 1.0


async def activate_promo(request):
    init_data = request.headers.get("X-Init-Data", "")
    user_data = verify_telegram_data(init_data) if init_data else None
    
    body = await request.json()
    if not user_data:
        user_id = body.get("user_id")
        if user_id:
            user_data = {"id": int(user_id)}
    
    if not user_data:
        return web.json_response({"error": "Unauthorized"}, status=401, headers=cors_headers())
    
    code = body.get("code", "").strip().upper()
    result = db.activate_promo(user_data["id"], code)
    
    if result["success"]:
        return web.json_response(result, headers=cors_headers())
    
    errors = {
        "not_found": "Промокод не найден",
        "expired": "Промокод больше не активен",
        "already_used": "Вы уже использовали этот промокод",
    }
    return web.json_response(
        {"error": errors.get(result["error"], "Ошибка")},
        status=400, headers=cors_headers()
    )


async def get_history(request):
    init_data = request.headers.get("X-Init-Data", "")
    user_data = verify_telegram_data(init_data) if init_data else None
    
    if not user_data:
        user_id = request.rel_url.query.get("user_id")
        if user_id:
            user_data = {"id": int(user_id)}
    
    if not user_data:
        return web.json_response({"error": "Unauthorized"}, status=401, headers=cors_headers())
    
    history = db.get_game_history(user_data["id"])
    return web.json_response({"history": history}, headers=cors_headers())


async def get_top(request):
    top = db.get_top_deposits(10)
    return web.json_response({"top": top}, headers=cors_headers())


async def play_upgrade(request):
    init_data = request.headers.get("X-Init-Data", "")
    user_data = verify_telegram_data(init_data) if init_data else None
    body = await request.json()
    if not user_data:
        user_id = body.get("user_id")
        if user_id:
            user_data = {"id": int(user_id)}
    if not user_data:
        return web.json_response({"error": "Unauthorized"}, status=401, headers=cors_headers())
    user_id = user_data["id"]
    bet = int(body.get("bet", 100))
    mult = float(body.get("mult", 2))
    is_win = bool(body.get("win", False))
    if is_win:
        win_amount = int(bet * mult)
        if not db.deduct_balance(user_id, bet):
            return web.json_response({"error": "Insufficient balance"}, status=400, headers=cors_headers())
        db.add_balance(user_id, win_amount)
        db.add_game_history(user_id, "upgrade", bet, f"win x{mult}", win_amount)
    else:
        if not db.deduct_balance(user_id, bet):
            return web.json_response({"error": "Insufficient balance"}, status=400, headers=cors_headers())
        db.add_game_history(user_id, "upgrade", bet, "lose", 0)
    return web.json_response({"balance": db.get_balance(user_id)}, headers=cors_headers())


game_sessions = {}


def create_app():
    import os
    webapp_path = os.path.join(os.path.dirname(__file__), "..", "webapp")
    webapp_path = os.path.abspath(webapp_path)
    index_path = os.path.join(webapp_path, "index.html")

    async def serve_index(request):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return web.Response(text=content, content_type="text/html", charset="utf-8")
    
    app = web.Application()
    app.router.add_route("GET", "/", serve_index)
    app.router.add_get("/api/user", get_user)
    app.router.add_post("/api/slots/play", play_slots)
    app.router.add_post("/api/mines/play", play_mines)
    app.router.add_post("/api/promo/activate", activate_promo)
    app.router.add_get("/api/history", get_history)
    app.router.add_get("/api/top", get_top)
    app.router.add_post("/api/upgrade/play", play_upgrade)
    app.router.add_static("/static", path=webapp_path, name="static")
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=8080)
