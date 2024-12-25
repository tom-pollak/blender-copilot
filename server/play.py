# %%
from fasthtml.common import *
from fasthtml.jupyter import JupyUvi, HTMX
from fasthtml.common import fast_app

# %%
app, rt = fast_app(pico=True)
server = JupyUvi(app)

# %%
HTMX()

# %%

@rt
def index():
    return Titled("Hello World!",
                  P("Welcome to this example"),
                  Button("Click me", hx_get="/click", hx_target="#dest"),
                  Div(id="dest"))

# %%

# #%%

@rt
def click():
    return Div(P("You clicked the button!"), id="dest")
