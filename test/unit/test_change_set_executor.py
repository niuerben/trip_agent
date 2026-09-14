from backend.app.models.schemas import (
    Attraction, ChangeOperation, ChangeSelector, ChangeSet, ChangeTarget, DayPlan,
    Location, TripPlan, TripRequest,
)
from backend.app.services.change_set_executor import ChangeSetExecutor
from backend.app.services.planning_context import PlanningContext, POIRecord


class Resolver:
    def __init__(self, result=None): self.result = result
    def resolve_attraction(self, target, context): return self.result


def make_plan():
    attraction = Attraction(name="Old Museum", address="A", location=Location(longitude=1, latitude=2), visit_duration=60, description="museum")
    return TripPlan(city="Test", start_date="2026-01-01", end_date="2026-01-02", days=[
        DayPlan(date="2026-01-01", day_index=0, description="d1", transportation="walk", accommodation="hotel", attractions=[attraction]),
        DayPlan(date="2026-01-02", day_index=1, description="d2", transportation="walk", accommodation="hotel"),
    ], overall_suggestions="ok")


def request():
    return TripRequest(city="Test", start_date="2026-01-01", end_date="2026-01-02", travel_days=2, transportation="walk", accommodation="hotel")


def context(): return PlanningContext(city="Test")


def test_replace_is_atomic_and_does_not_mutate_inputs():
    plan, req = make_plan(), request()
    result = ChangeSetExecutor(Resolver(POIRecord(name="New Park", longitude=3, latitude=4))).execute(
        plan, req, context(), ChangeSet(operations=[ChangeOperation(operation="replace_attraction", selector=ChangeSelector(name="Old Museum"), target=ChangeTarget(name="New Park"))]))
    assert plan.days[0].attractions[0].name == "Old Museum"
    assert result.plan.days[0].attractions[0].name == "New Park"
    assert isinstance(result.changes, tuple)


def test_replace_rejects_ambiguous_selector():
    plan, req = make_plan(), request()
    plan.days[1].attractions.append(plan.days[0].attractions[0].model_copy(deep=True))
    import pytest
    with pytest.raises(Exception) as error:
        ChangeSetExecutor(Resolver(POIRecord(name="X", longitude=3, latitude=4))).execute(plan, req, context(), ChangeSet(operations=[ChangeOperation(operation="replace_attraction", selector=ChangeSelector(name="Old"), target=ChangeTarget(name="X"))]))
    assert error.value.code == "ambiguous_selector"


def test_update_dates_and_day():
    result = ChangeSetExecutor(Resolver()).execute(make_plan(), request(), context(), ChangeSet(operations=[
        ChangeOperation(operation="update_dates", fields={"start_date": "2026-02-01", "end_date": "2026-02-02"}),
        ChangeOperation(operation="update_day", selector=ChangeSelector(day_index=1), fields={"description": "updated"}),
    ]))
    assert result.plan.days[0].date == "2026-02-01"
    assert result.plan.days[1].description == "updated"


def test_full_replan_is_rejected():
    import pytest
    with pytest.raises(Exception) as error:
        ChangeSetExecutor(Resolver()).execute(make_plan(), request(), context(), ChangeSet(operations=[ChangeOperation(operation="full_replan")]))
    assert error.value.code == "full_replan_not_supported"
