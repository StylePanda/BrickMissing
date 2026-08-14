from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import AuditEvent

from .forms import PrivateDocumentForm
from .models import PrivateDocument


@login_required
def document_list(request):
    documents = PrivateDocument.objects.filter(owner=request.user, deleted_at__isnull=True)
    return render(request, "media_library/list.html", {"documents": documents})


@login_required
def upload(request):
    form = PrivateDocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.owner = request.user
        document.original_name = Path(form.cleaned_data["file"].name).name[:255]
        document.mime_type = form.cleaned_data["file"].validated_mime
        document.size = form.cleaned_data["file"].size
        document.save()
        AuditEvent.objects.create(
            actor=request.user,
            target_user=request.user,
            action="document.uploaded",
            entity_type="document",
            entity_id=str(document.pk),
            request_id=request.request_id,
        )
        return redirect("media_library:list")
    return render(
        request, "media_library/form.html", {"form": form, "title": "Privates Dokument hochladen"}
    )


@login_required
def download(request, pk):
    document = get_object_or_404(
        PrivateDocument, pk=pk, owner=request.user, deleted_at__isnull=True
    )
    response = FileResponse(
        document.file.open("rb"),
        content_type=document.mime_type,
        as_attachment=True,
        filename=document.original_name,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def delete(request, pk):
    from django.utils import timezone

    document = get_object_or_404(
        PrivateDocument, pk=pk, owner=request.user, deleted_at__isnull=True
    )
    document.deleted_at = timezone.now()
    document.save(update_fields=["deleted_at"])
    AuditEvent.objects.create(
        actor=request.user,
        target_user=request.user,
        action="document.trashed",
        entity_type="document",
        entity_id=str(document.pk),
        request_id=request.request_id,
    )
    return redirect("media_library:list")
