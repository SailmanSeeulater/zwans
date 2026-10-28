from webapp.router import Router

router = Router()


@router.route("/stats")
def stats(request):
    return "stats"


@router.route("/users/<user_id>/ban", methods=("POST", "DELETE"))
def ban(request):
    return "ban"
