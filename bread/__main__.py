"""python -m bread [--port 8000]: run the site. DATABASE_URL picks the database (SQLite by default)."""

import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="bread")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    if os.path.exists(".env"):  # local runs: load LLM_API_KEY and friends without exporting them
        with open(".env", encoding="utf-8") as env:
            for line in env:
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ.setdefault(key, value)
    import uvicorn

    from .app import admin_token_hint, create_app

    app = create_app()
    print(f"bread: http://localhost:{args.port}   admin token: {admin_token_hint()}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
