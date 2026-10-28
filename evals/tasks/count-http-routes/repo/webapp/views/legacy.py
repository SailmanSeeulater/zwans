"""The v0 endpoints. Nothing mounts this router any more."""

from webapp.router import Router

router = Router()


@router.route("/getUser")
def get_user(request):
    return "user"


@router.route("/listOrders")
def list_orders(request):
    return "orders"
