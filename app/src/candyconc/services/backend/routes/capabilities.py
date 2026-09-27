"""Product-level capability contract route."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from candyconc.capabilities import build_product_capability_contract
from candyconc.entrypoints.errors import CandyAPIRouter
from candyconc.i18n import localize
from .. import auth
from ..schemas import ProductCapabilityContractResponse


router = CandyAPIRouter()


@router.get(
    "/capabilities",
    response_model=ProductCapabilityContractResponse,
    tags=["capabilities"],
)
async def product_capabilities_route(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> ProductCapabilityContractResponse:
    """Return the product contract shared by backend, UI, and Copilot audits."""
    # The response model has str fields, which would keep only the German text
    # of each pair. Resolve the texts to the request language first.
    return ProductCapabilityContractResponse(**localize(build_product_capability_contract()))
