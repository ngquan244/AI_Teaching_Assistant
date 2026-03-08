#!/usr/bin/env python
"""
Teaching Assistant Grader - Application Entry Point

Usage:
    python run.py [--host HOST] [--port PORT] [--reload]

Examples:
    python run.py                    # Start with defaults
    python run.py --reload           # Start with auto-reload
    python run.py --port 8000        # Start on custom port
"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(
        description="Teaching Assistant Grader API Server"
    )
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Host to bind (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000, 
        help="Port to bind (default: 8000)"
    )
    parser.add_argument(
        "--reload", 
        action="store_true", 
        help="Enable auto-reload for development"
    )
    
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
            Teaching Assistant Grader API Server               
╠══════════════════════════════════════════════════════════════╣
    Host: {args.host:<15}                                      
    Port: {args.port:<15}                                      
    Reload: {'Enabled' if args.reload else 'Disabled':<12}     
╠══════════════════════════════════════════════════════════════╣
    API Docs: http://{args.host}:{args.port}/docs              
    ReDoc:    http://{args.host}:{args.port}/redoc             
╚══════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
