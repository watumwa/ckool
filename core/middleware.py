import time
from django.shortcuts import redirect
from core.settings import common

class AutoLogoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Get last activity time (default to current time if not found)
            last_activity = request.session.get('last_activity', time.time())

            # Calculate elapsed time
            elapsed_time = time.time() - last_activity

            # If inactive for more than SESSION_COOKIE_AGE, log out the user
            if elapsed_time > common.SESSION_COOKIE_AGE:
                request.session.flush()  # Clears session (logs out the user)
                return redirect('login')  # Redirect to login page

            # Update last activity timestamp
            request.session['last_activity'] = time.time()

        response = self.get_response(request)
        return response
