#!/usr/bin/env python
"""
Application entry point for the Listing App.

This module initializes and runs the Flask web application. It reads
the environment configuration from environment variables and starts
the web server on the specified port.
"""
import os
from app import create_app

# Determine which environment configuration to use (development or production)
config_name = os.environ.get('FLASK_ENV', 'development')

# Create and configure the Flask application instance
app = create_app(config_name)

if __name__ == '__main__':
    # Get the server port from environment variables, defaulting to 8000
    port = int(os.environ.get('PORT', 8000))
    
    # Start the application server on all network interfaces
    app.run(
        host='0.0.0.0',
        port=port,
        debug=app.config.get('DEBUG', False)
    )
