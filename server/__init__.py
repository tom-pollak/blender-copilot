from fasthtml.common import *
from .oauth_auth import init_auth, user_authenticated

app = fast_app()
oauth = init_auth(app)

@app.get('/')
@user_authenticated
async def home(request):
    user = request.session['user']
    return f"Welcome {user['name']}!"

# Protected route example
@app.get('/protected')
@user_authenticated
async def protected(request):
    return "This is a protected route"

serve()
