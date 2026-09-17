import argparse
from pathlib import Path

import uvicorn
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description="Serve a verified immutable MarketRank release locally")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8070)
    args = parser.parse_args()
    app = create_app(args.release, host=args.host)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
