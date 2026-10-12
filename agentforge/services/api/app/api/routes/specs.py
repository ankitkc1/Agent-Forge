from fastapi import APIRouter

from app.schemas.agent_spec import CompileRequest, CompileResponse
from app.services.compiler import compile_requirement, spec_hash

router = APIRouter(prefix="/specs", tags=["specs"])


@router.post("/compile", response_model=CompileResponse)
def compile_spec(payload: CompileRequest) -> CompileResponse:
    spec, warnings = compile_requirement(payload.requirement)
    return CompileResponse(spec=spec, spec_hash=spec_hash(spec), warnings=warnings)
