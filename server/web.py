# fmt: off
from fasthtml.common import *
from datetime import datetime

from server.plans import PLAN_LIMITS

from .app import rt, oauth
from .users import get_authenticated_user


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
                   href="/login"),
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
async def profile(req):
    user = get_authenticated_user(req)
    tok_display = f"{user.api_token[:12]}...{user.api_token[-8:]}"
    calls_left = PLAN_LIMITS[user.plan] - user.daily_calls

    def fmt_rel(date_str: str) -> str:
        dt = datetime.fromisoformat(date_str)
        delta = datetime.now() - dt

        if delta.days > 0: return f"{delta.days}d ago"
        h = delta.seconds // 3600
        if h > 0: return f"{h}h ago"
        m = delta.seconds // 60
        if m > 0: return f"{m}m ago"
        return "just now"

    copy_js = Script("""
        function copyToken() {
            const tok = document.getElementById('api-token');
            navigator.clipboard.writeText(tok.textContent);
            const icon = document.getElementById('copy-icon');
            const txt = document.getElementById('copy-text');
            txt.textContent = 'Copied!';
            icon.classList.add('hidden');
            setTimeout(() => {
                txt.textContent = 'Copy';
                icon.classList.remove('hidden');
            }, 2000);
        }
    """)

    icons = Link(
        rel="stylesheet",
        href="https://cdnjs.cloudflare.com/ajax/libs/remixicon/4.6.0/remixicon.min.css"
    )

    user_info = Div(
        I(cls="ri-account-circle-2-fill text-4xl text-white h-12 w-12 rounded-full bg-blue-600 flex items-center justify-center"),
        Div(
        H1(f"Welcome, {user.name}!", cls="text-3xl font-bold text-white"),
            Div(
                Div(cls="w-2 h-2 rounded-full bg-green-400"),
                P(f"{user.plan.capitalize()} Plan · Active",
                  cls="text-sm text-slate-400 ml-2"),
                cls="flex items-center mt-1"
            ),
            cls="ml-4"
        ),
        cls="flex items-center"
    )

    upgrade_text = "Upgrade" if user.plan == "free" else "Manage Subscription"
    upgrade_icon = "ri-arrow-up-circle-line" if user.plan == "free" else "ri-settings-3-line"
    upgrade_button = A(
        I(cls=f"{upgrade_icon} mr-2"),
        upgrade_text,
        href="/subscription",
        cls="inline-flex items-center px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
    )

    header = Div(
        Div(
            user_info,
            upgrade_button,
            cls="flex items-center justify-between"
        ),
        cls="mb-8"
    )

    stats = Div(
        Div(I(cls="ri-bar-chart-fill text-blue-400 text-xl"),
        P("API Calls Today", cls="text-sm text-slate-400 mt-1"),
            Div(
                P(f"{format(user.daily_calls, ',')} / {format(PLAN_LIMITS[user.plan], ',')}",
                  cls="text-2xl font-semibold"),
                P(f"{format(calls_left, ',')} calls remaining",
                  cls="text-xs text-slate-400 mt-1"),
                cls="text-center"
            ),
            cls="text-center px-12"
        ),
        Div(
            I(cls="ri-time-fill text-blue-400 text-xl"),
            P("Last API Call", cls="text-sm text-slate-400 mt-1"),
            P(fmt_rel(user.last_call_time), cls="text-2xl font-semibold"),
            cls="text-center px-12 border-l border-slate-800"
        ),
        cls="flex justify-center mb-8 bg-slate-950/50 rounded-lg py-4"
    )

    _license = Div(
        Div(
            I(cls="ri-key-2-fill text-slate-400"),
            P("Your License Key", cls="ml-2 text-md text-slate-400"),
            cls="flex items-center mb-2"
        ),
        Div(
            Div(
                P(user.api_token, id="api-token", cls="hidden"),
                P(tok_display, cls="font-mono text-sm"),
                Div(
                    Button(
                        Span("Copy", id="copy-text"),
                        I(cls="ri-clipboard-line ml-2", id="copy-icon"),
                        onclick="copyToken()",
                        cls="flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                    ),
                    cls="ml-3"
                ),
                cls="flex items-center justify-between bg-slate-950 p-3 rounded-lg"
            ),
            cls="max-w-2xl"
        ),
        cls="space-y-4"
    )

    footer = Div(
    Div(
        P(f"Last login: {fmt_rel(user.last_login)}", cls="text-sm text-slate-500 mt-1"),
            P(f"Email: {user.email}", cls="text-sm text-slate-500 mt-1")
        ),
        A(
            I(cls="ri-logout-box-r-line mr-2"),
            "Log out",
            href="/logout",
            cls="inline-flex items-center px-4 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors"
        ),
        cls="flex items-center justify-between mt-8 pt-6 border-t border-slate-800"
    )

    card = Div(
        header,
        stats,
        _license,
        footer,
        cls="max-w-2xl mx-auto bg-slate-900 border border-slate-800 rounded-xl p-6"
    )

    page = Div(
        Div(cls="absolute top-0 left-0 w-full h-64 bg-gradient-to-br from-blue-600/10 to-purple-600/10"),
        Div(card, cls="relative z-10 max-w-4xl mx-auto"),
        cls="min-h-screen bg-slate-950 text-white p-8 relative"
    )

    return Main(
        copy_js,
        icons,
        page,
    )

PLAN_FEATURES = {
    "free": {
        "price": 0,
        "features": [
            f"Up to {format(PLAN_LIMITS['free'], ',')} API calls per day",
            "Basic features",
            "Community support",
            "Standard response time"
        ]
    },
    "premium": {
        "price": 29,
        "features": [
            f"Up to {format(PLAN_LIMITS['premium'], ',')} API calls per day",
            "Advanced features",
            "Priority support",
            "Custom configurations",
            "Usage analytics"
        ]
    }
}

@rt
def subscription(req):
    user = get_authenticated_user(req)

    icons = Link(
        rel="stylesheet",
        href="https://cdnjs.cloudflare.com/ajax/libs/remixicon/4.6.0/remixicon.min.css"
    )

    header = Div(
        H1("Choose Your Plan", cls="text-3xl font-bold text-white mb-2"),
        P("Upgrade to unlock higher API limits and advanced features",
          cls="text-slate-400 mb-8"),
        cls="text-center"
    )

    def plan_card(plan_name):
        plan = PLAN_FEATURES[plan_name]
        is_current = user.plan == plan_name

        return Div(
            Div(
                H2(plan_name.capitalize(), cls="text-xl font-bold mb-1"),
                P(f"${plan['price']}/month", cls="text-2xl font-bold text-blue-400"),
                cls="mb-6"
            ),
            Div(
                *[Div(
                    I(cls="ri-check-line mr-2 text-blue-400"),
                    P(feature, cls="text-slate-300"),
                    cls="flex items-center mb-3"
                ) for feature in plan['features']],
                cls="flex-grow"
            ),
            Button(
                "Current Plan" if is_current else "Upgrade Now",
                disabled=is_current,
                cls=f"""w-full px-4 py-3 rounded-lg transition-colors mt-6
                    {"bg-slate-800 text-slate-400 cursor-not-allowed" if is_current else
                     "bg-blue-600 text-white hover:bg-blue-700"}"""
            ),
            cls=f"""p-6 bg-slate-900 border
                {"border-blue-600" if is_current else "border-slate-800"}
                rounded-xl flex flex-col h-full"""
        )

    plans = Div(
        *[plan_card(plan_name) for plan_name in PLAN_FEATURES.keys()],
        cls="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8 max-w-4xl mx-auto"
    )

    footer = Div(
        A(
            I(cls="ri-arrow-left-line mr-2"),
            "Back to Profile",
            href="/profile",
            cls="inline-flex items-center px-4 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors"
        ),
        cls="flex justify-center"
    )

    content = Div(
        Div(cls="absolute top-0 left-0 w-full h-64 bg-gradient-to-br from-blue-600/10 to-purple-600/10"),
        Div(
            header,
            plans,
            footer,
            cls="relative z-10 max-w-5xl mx-auto"
        ),
        cls="min-h-screen bg-slate-950 text-white p-8 relative"
    )

    return Main(
        icons,
        content
    )
