#!/usr/bin/env python3
"""Script to run the API server"""
import uvicorn
import os
import sys

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    
    uvicorn.run(
        "src.server.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )


