from webapp.router import Router

router = Router()


@router.route("/")
def orders(request):
    return "orders"


@router.route("/<order_id>", methods=("get", "patch"))
def order(request):
    return "order"


@router.route("/<order_id>/cancel", methods=("POST",))
def cancel(request):
    return "cancelled"


def refund(request):
    return "refunded"


router.add("POST", "/<order_id>/refund", refund)
router.add("post", "/<order>/refund/", refund)
