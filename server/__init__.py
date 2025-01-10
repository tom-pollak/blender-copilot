# register routes
from .web import home, profile
from .subscriptions import manage_billing, stripe_webhook
from .infer_api import text_to_3d, image_to_3d
