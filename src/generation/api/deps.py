from fastapi import Request

from generation.application.workflow import Workflow


def get_workflow(request: Request) -> Workflow:
    return request.app.state.workflow
