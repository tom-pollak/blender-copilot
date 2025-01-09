# fmt: off
from fasthtml.common import *

from .app import rt, oauth
from .users import User, get_user

__all__ = ["home", "profile"]

@rt("/")
async def home(request):
    hdrs = Style("""
            body {
                background: #080808;
            }
            .main-video {
                width: 100%;
                height: 100vh;
                object-fit: cover;
            }
            .nav-backdrop {
                background: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 100%);
                height: 120px;
                pointer-events: none;
                top: 0;
            }
            .nav-content {
                pointer-events: auto;
            }
        """)

    header = Header(
        Div(cls="nav-backdrop absolute w-full"),
        Div(Span("Blender Copilot", cls="text-lg font-medium"),
            A("Login",
                   cls="text-sm px-4 py-2 bg-white/10 rounded-lg backdrop-blur-sm hover:bg-white/20 transition-colors",
                   href=oauth.login_link(request)),
            cls="nav-content flex justify-between items-center py-6 px-12 relative"),
        cls="fixed w-full z-50",
    )

    video_section = Div(
        Video(
            Source(src="/static/roof_trashcan.mp4", type="video/mp4"),
            autoplay=True,
            muted=True,
            loop=True,
            playsinline=True,
            cls="main-video",
        ),
        Div(
            Div(
                H1(
                    "Transform text and images into 3D instantly",
                    cls="font-medium mb-4 leading-tight",
                    style="font-size: min(8vw, 3rem)",
                ),
                Button(
                    "TRY IT FOR FREE",
                    cls="text-sm sm:text-base whitespace-nowrap px-6 py-3 bg-white text-black rounded-lg font-medium hover:bg-opacity-90 transition-colors",
                ),
                cls="max-w-3xl",
            ),
            cls="absolute bottom-0 left-0 p-12 w-full bg-gradient-to-t from-black to-transparent",
        ),
        cls="relative",
    )

    showcase = Div(
        Div(
            Div(
                P(
                    "See what's possible with Blender Copilot",
                    cls="text-lg text-gray-400 max-w-md",
                ),
                cls="mb-16",
            ),
            Img(
                src="static/mesh-samples.gif",
                alt="3D Mesh Samples",
                cls="w-full rounded-xl",
            ),
            cls="max-w-7xl mx-auto",
        ),
        cls="px-12 py-24",
    )

    return Main(
        hdrs,
        header,
        video_section,
        showcase,
        cls="text-white"
    )

@rt
async def profile(request):
    user_id = request.session["user_id"]
    user = get_user(user_id)
    assert user is not None, "User not found in authenticated session"
    return P(f"Welcome {user.name}!"), A('Log out', href='/logout')
