# %%
from fastlite import *

db = database("server/data/main.db")

db.t

# %%

users = db.t.user

# %%
db.q("select * from user")

# %%

me = users["103902157978598749415"]
me['stripe_customer_id'] = 'cus_RYrd5qis85HmF2'
me['plan'] = 'premium'
users.update(me)

# %%


db.q("select * from user")

# %%
from fasthtml.common import *

a = Main(
    H1("401", style="margin:30px 0; font-size:4em; line-height:1; letter-spacing:-1px; font-family: Times; font-weight: bold"),
    P(Strong("Unauthorized :(", style="font-family: Times; font-weight: bold")),
    style="margin:10px auto; max-width:600px; text-align:center"
)

a
# %%

a.__html__??

# %%

print((a))
