import os, datetime
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))[os.getenv("MONGO_DB")]

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

for src in ["medicines", "medicine_market"]:
    dst = f"{src}_backup_{ts}"
    db[src].aggregate([{"$match": {}}, {"$out": dst}])
    print("backup done:", src, "->", dst)
