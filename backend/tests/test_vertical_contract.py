import json
from pathlib import Path
from typing import Any, Protocol, cast
import jsonschema
import pytest
from app.bootstrap import create_app
from app.modules.events.presentation import CreateEvent
from app.modules.discovery.presentation import NearbyInput
from tests.test_foundation import settings, Probe


class Validator(Protocol):
    def validate(self,value: object) -> None: ...


def test_multiline_description_is_preserved_without_allowing_title_controls() -> None:
    from tests.test_events import event_body
    description='Primeira linha\nSegunda linha\tDetalhe'
    assert CreateEvent.model_validate(event_body(description=description)).value().description==description
    for changes in ({'title':'Title\nforged'},{'location_label':'Place\rforged'},{'description':'Null\x00byte'}):
        with pytest.raises(ValueError):CreateEvent.model_validate(event_body(**changes))


def test_synthetic_examples_and_independent_consumer_contract() -> None:
    directory=Path("contracts") if Path("contracts").exists() else Path("../contracts")
    example: dict[str,Any]=json.loads((directory/"fixtures/vertical-05a.json").read_text(encoding="utf-8"))
    CreateEvent.model_validate(example["create"])
    NearbyInput.model_validate(example["nearby"])
    schema=create_app(settings(),Probe(True)).openapi()
    creation=schema["paths"]["/api/v1/events"]["post"]
    key=next(header for header in creation["parameters"] if header["name"]=="idempotency-key")
    assert key["required"] and key["schema"]["format"]=="uuid"
    assert {"201","409","401","422"}.issubset(creation["responses"])
    assert "Location" in creation["responses"]["201"]["headers"] and "ETag" in creation["responses"]["201"]["headers"]
    for path,method in (("/api/v1/events","post"),("/api/v1/events/{event_id}","get"),
                        ("/api/v1/discovery/nearby","post"),("/api/v1/events/{event_id}/updates","get")):
        operation=schema["paths"][path][method]
        assert operation["security"]==[{"FirebaseIDToken":[]}]
        for response in operation["responses"].values():assert "X-Correlation-ID" in response["headers"]
    for name,body in (("CreateEvent",example["create"]),("NearbyInput",example["nearby"])):
        validator=cast(Validator,jsonschema.Draft202012Validator(schema["components"]["schemas"][name]))
        validator.validate(body)
        with pytest.raises(jsonschema.ValidationError):validator.validate({**body,"organizer_id":"forged"})
    assert "text/event-stream" in schema["paths"]["/api/v1/events/{event_id}/updates"]["get"]["responses"]["200"]["content"]
    assert not any(name in schema["components"]["schemas"]["NearbyItem"]["properties"]
                   for name in ("organizer_id","email","subject","issuer","longitude","latitude"))
