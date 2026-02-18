import time
import argparse
from pymongo import UpdateOne
from scrapers.utils.mongo import get_collection


def now_ts() -> int:
    return int(time.time())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--batch", type=int, default=1000)
    p.add_argument("--log-every", type=int, default=1000)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    col = get_collection("medicine_market")

    proj = {"_id": 1, "country": 1, "cis": 1}
    cur = col.find({}, proj)
    if args.limit:
        cur = cur.limit(args.limit)

    ops = []
    scanned = 0
    queued = 0
    updated = 0
    skipped = 0

    for doc in cur:
        scanned += 1
        country = doc.get("country")
        cis = doc.get("cis")

        if not country or not cis:
            skipped += 1
            continue

        source = "BDPM"
        market_key = f"{country}|{source}|{cis}"

        ops.append(UpdateOne(
            {"_id": doc["_id"]},
            {"$set": {"market_key": market_key, "updated_at": now_ts()}}
        ))
        queued += 1

        if scanned % args.log_every == 0:
            print(f"[scan={scanned}] queued={queued} ops_pending={len(ops)} updated={updated} skipped={skipped}")

        if len(ops) >= args.batch:
            if not args.dry_run:
                res = col.bulk_write(ops, ordered=False)
                updated += res.modified_count
            ops = []

    if ops and not args.dry_run:
        res = col.bulk_write(ops, ordered=False)
        updated += res.modified_count

    print("\n=== BACKFILL MARKET_KEY DONE ===")
    print(f"scanned={scanned}")
    print(f"queued={queued}")
    print(f"updated_modified={updated} (dry-run={args.dry_run})")
    print(f"skipped_missing_country_or_cis={skipped}")


if __name__ == "__main__":
    main()
