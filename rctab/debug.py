"""Used as an entrypoint when debugging from an IDE."""
import uvicorn

from rctab.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
