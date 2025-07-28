#!/usr/bin/env python3
"""
Development server runner for Giani AI Project Knowledge Base.
"""
from main import app

if __name__ == '__main__':
    print("Starting Giani AI Project Knowledge Base development server...")
    print("API available at: http://localhost:8000")
    print("Test endpoints:")
    print("  - Home: http://localhost:8000/")
    print("\nPress Ctrl+C to stop the server.")

    app.run(
        debug=True,
        host='0.0.0.0',
        port=8000,
        use_reloader=True
    )