from django.http import JsonResponse


def home(_request):
	return JsonResponse({"status": "ok"})

# Create your views here.
