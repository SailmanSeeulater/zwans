from webapp.router import Router

router = Router()


@router.route("/", methods=("GET", "POST"))
def users(request):
    return "users"


@router.route("/<user_id>", methods=("GET", "PUT", "DELETE"))
def user(request):
    return "user"


@router.route("/<id>/")
def user_again(request):
    return "user (trailing slash)"


@router.route("/<user_id>/avatar", methods=("GET", "PUT"))
def avatar(request):
    return "avatar"
