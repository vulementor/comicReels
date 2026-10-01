"""Browser transport status and preflight projection."""
from fastapi import APIRouter, Response

from agent.services.flow_backend_status import read_backend_status

router = APIRouter(prefix='/flow', tags=['flow'])


@router.get('/backend-status')
async def backend_status(response: Response):
    """Report configuration and observed readiness without authorizing effects."""
    response.headers['Cache-Control'] = 'no-store'
    return await read_backend_status()
