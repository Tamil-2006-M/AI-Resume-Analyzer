# Procfile - tells Render, Railway and Heroku how to start the app.
#
#   web:                this process serves HTTP
#   gunicorn            the production server (Linux only)
#   wsgi:application    the file wsgi.py, variable "application"
#   --workers 2         two processes, so one slow request does not
#                       block everyone else
#   --timeout 120       allow 120s per request; an AI call can be slow
#   --bind 0.0.0.0:$PORT  the host sets $PORT; we must use whatever it gives
web: gunicorn wsgi:application --workers 2 --timeout 120 --bind 0.0.0.0:$PORT
