import asyncio, datetime, json, os
import jwt
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

env = dotenv_values("/app/backend/.env")
SECRET = env["JWT_SECRET"]

async def main():
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]
    u = await db.hub_users.find_one({"email": "davibraga0706@gmail.com"})
    print("admin _id:", u["_id"], "ver:", u.get("token_version", 0), "hash_prefix:", u["password_hash"][:4])
    now = datetime.datetime.now(datetime.timezone.utc)
    uid = str(u["_id"])
    ver = u.get("token_version", 0)
    expired_access = jwt.encode({"sub": uid, "email": u["email"], "ver": ver,
                                 "exp": now - datetime.timedelta(minutes=5), "type": "access"},
                                SECRET, algorithm="HS256")
    valid_refresh = jwt.encode({"sub": uid, "ver": ver,
                                "exp": now + datetime.timedelta(days=6), "type": "refresh"},
                               SECRET, algorithm="HS256")
    bad = jwt.encode({"sub": uid, "ver": ver, "exp": now - datetime.timedelta(days=1),
                      "type": "refresh"}, SECRET, algorithm="HS256")
    out = {"uid": uid, "expired_access": expired_access, "valid_refresh": valid_refresh,
           "expired_refresh": bad}
    print(json.dumps(out, indent=1))
    open("/app/test_reports/tokens.json", "w").write(json.dumps(out))

asyncio.run(main())
