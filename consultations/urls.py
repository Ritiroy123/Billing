from rest_framework.routers import SimpleRouter
from .views import SessionViewSet

router = SimpleRouter()
router.register("sessions", SessionViewSet, basename="session")
urlpatterns = router.urls
