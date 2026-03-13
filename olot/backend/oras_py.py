import os
import typing


def is_oras_py() -> bool:
    """Check if the oras Python library is available."""
    try:
        import oras  # noqa: F401
        return True
    except ImportError:
        return False


def _extract_hostname(reference: str) -> str:
    """Extract the registry hostname from an OCI image reference.
    """
    ref = reference.split("@")[0]
    if "/" not in ref:
        # Bare image name (e.g. "busybox:latest") implies docker.io
        return "docker.io"
    first_component = ref.split("/")[0]
    if "." in first_component or first_component.startswith("localhost"):
        return first_component
    return "docker.io"


def _setup_auth(registry: "typing.Any", reference: str) -> None:
    """Load authentication configs for the registry hostname in the reference."""
    hostname = _extract_hostname(reference)
    registry.auth.hostname = hostname
    registry.auth.load_configs(hostname)


def _normalize_docker_hub(reference: str) -> str:
    """Rewrite docker.io/ hostname references to use registry-1.docker.io/ directly instead.
    """
    return reference.replace("docker.io/", "registry-1.docker.io/", 1)


def oras_py_pull(base_image: str, dest: typing.Union[str, os.PathLike], *, insecure: bool = False, tls_verify: bool = True) -> None:
    """Pull an image from a registry to a local OCI layout directory using oras-py."""
    from oras.provider import Registry
    from oras.layout.layout import NewLayoutFromRegistry

    if isinstance(dest, os.PathLike):
        dest = str(dest)

    base_image = _normalize_docker_hub(base_image)
    registry = Registry(insecure=insecure, tls_verify=tls_verify)
    _setup_auth(registry, base_image)
    NewLayoutFromRegistry(path=dest, provider=registry, target=base_image, tag="latest")


def _preseed_push_token(registry: "typing.Any", oci_ref: str) -> None:
    """Pre-seed a push-scoped auth token on the registry.

    Workaround for oras-py token scope caching bug (oras-project/oras-py#133):
    push_to_registry internally calls blob_exists (HEAD) which caches a pull-only
    token. Subsequent upload (POST) fails because the cached token lacks push scope
    and oras-py does not re-negotiate on 401.
    By pre-seeding a push-scoped token, all subsequent requests use the correct scope.
    """
    import requests as _requests
    from oras.auth.utils import parse_auth_header

    hostname = _extract_hostname(oci_ref)
    # Strip tag/digest to get the repository path
    ref_no_tag = oci_ref.split(":")[0] if ":" in oci_ref else oci_ref
    repo_path = ref_no_tag.split("/", 1)[1] if "/" in ref_no_tag else ref_no_tag
    scheme = "http" if registry._tls_verify is False else "https"
    resp = _requests.post(f"{scheme}://{hostname}/v2/{repo_path}/blobs/uploads/")
    www_auth = resp.headers.get("Www-Authenticate")
    if www_auth:
        h = parse_auth_header(www_auth)
        token = registry.auth.request_token(h)
        if token:
            registry.auth.token = token


def oras_py_push(src: typing.Union[str, os.PathLike], oci_ref: str, *, insecure: bool = False, tls_verify: bool = True) -> None:
    """Push a local OCI layout directory to a registry using oras-py."""
    from oras.provider import Registry
    from oras.layout.layout import NewLayout

    if isinstance(src, os.PathLike):
        src = str(src)

    oci_ref = _normalize_docker_hub(oci_ref)
    registry = Registry(insecure=insecure, tls_verify=tls_verify)
    _setup_auth(registry, oci_ref)
    _preseed_push_token(registry, oci_ref)
    layout = NewLayout(src)
    layout.push_to_registry(provider=registry, target=oci_ref, tag="latest")
