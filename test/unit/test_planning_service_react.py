"""受 Validator 约束的旅行规划 ReAct 循环测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.services.planning_service import (
    PlanningSession,
    PlanningToolset,
    ValidatedPlanningReActAgent,
)
from backend.app.models.schemas import Location, TripPlan, TripRequest
from backend.app.services.trip_plan_validator import collect_trip_plan_issues


class FakeLLM:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def invoke(self, messages, **_kwargs):
        self.calls += 1
        self.prompts.append(messages[-1]["content"])
        return next(self.responses)


def trip_request() -> TripRequest:
    return TripRequest(
        city="深圳坪山",
        start_date="2026-07-27",
        end_date="2026-07-27",
        travel_days=1,
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def valid_plan() -> dict:
    return {
        "city": "深圳坪山",
        "start_date": "2026-07-27",
        "end_date": "2026-07-27",
        "days": [{
            "date": "2026-07-27",
            "day_index": 0,
            "description": "校园与美食路线",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "hotel": {
                "name": "坪山中心酒店",
                "address": "坪山大道1号",
                "location": {"longitude": 114.401, "latitude": 22.700},
                "price_range": "200-300元",
                "rating": "4.5",
                "distance": "当日路线起终点",
                "type": "经济型酒店",
                "poi_id": "HOTEL1",
            },
            "attractions": [{
                "name": "深圳技术大学",
                "address": "兰田路3002号",
                "location": {"longitude": 114.399831, "latitude": 22.700708},
                "visit_duration": 120,
                "description": "校园参观",
                "category": "大学",
                "poi_id": "B0FFK4HFDB",
            }],
            "meals": [
                {
                    "type": meal_type,
                    "name": f"坪山真实餐馆{index}",
                    "address": f"坪山区测试路{index}号",
                    "location": {"longitude": 114.40 + index / 1000, "latitude": 22.70},
                    "description": "推荐招牌饭菜",
                    "estimated_cost": 35 + index,
                    "poi_id": f"POI{index}",
                }
                for index, meal_type in enumerate(("breakfast", "lunch", "dinner"), start=1)
            ],
        }],
        "weather_info": [],
        "overall_suggestions": "按校园开放时间游览",
    }


class ValidatedPlanningReActTest(unittest.TestCase):
    def setUp(self) -> None:
        # 测试使用假 POI；禁止把它们写进真实运行的 agent_loop.log。
        self.events = []
        self.log_patcher = patch(
            "backend.app.services.planning_service.log_agent_loop",
            side_effect=lambda event, _run_id, **fields: self.events.append((event, fields)),
        )
        self.log_patcher.start()

    def tearDown(self) -> None:
        self.log_patcher.stop()

    def test_validator_ignores_model_weather_owned_by_backend(self) -> None:
        payload = valid_plan()
        payload["weather_info"] = [{"weather": "晴", "temperature": "28-33℃"}]
        payload["days"][0]["day_index"] = 1
        payload["days"][0]["date"] = "2030-01-01"
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}

        result = json.loads(PlanningToolset(session).validate_draft(
            json.dumps(payload, ensure_ascii=False)
        ))

        self.assertTrue(result["passed"])
        self.assertEqual(session.validated_plan.weather_info, [])
        self.assertEqual(session.validated_plan.days[0].day_index, 0)
        self.assertEqual(session.validated_plan.days[0].date, "2026-07-27")

    def test_chroma_meal_candidate_becomes_validated_day_meal(self) -> None:
        """Chroma 餐馆先进入 search_poi 证据，再能进入最终 day.meals。"""
        cached_poi = {
            "poi_group": "meal",
            "poi_id": "CHROMA-MEAL-1",
            "name": "缓存客家餐厅",
            "address": "坪山路1号",
            "longitude": 114.401,
                    "latitude": 22.700,
                    "adcode": "440310",
                    "type": "餐饮服务;中餐厅",
            "cost": "36",
        }
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
            cached_pois=[
                {
                    **cached_poi,
                    "poi_id": f"CHROMA-MEAL-{index}",
                    "name": f"缓存客家餐厅{index}",
                    "address": f"坪山路{index}号",
                    "longitude": 114.401 + index / 1000,
                }
                for index in range(1, 4)
            ],
        )
        toolset = PlanningToolset(session)
        search_result = json.loads(toolset.search_poi(
            json.dumps({"purpose": "meal", "query": "客家菜", "category": "餐馆"})
        ))

        self.assertEqual(search_result["source"], "chroma")
        self.assertEqual(search_result["candidates"][0]["poi_id"], "CHROMA-MEAL-1")
        self.assertIn("CHROMA-MEAL-1", session.evidence_ids["meal"])

        payload = valid_plan()
        for index, meal in enumerate(payload["days"][0]["meals"], start=1):
            meal.update({
                "name": f"缓存客家餐厅{index}",
                "address": f"坪山路{index}号",
                "location": {"longitude": 114.401 + index / 1000, "latitude": 22.700},
                "description": "推荐酿豆腐",
                "estimated_cost": 36,
                "poi_id": f"CHROMA-MEAL-{index}",
            })
        validation = json.loads(toolset.validate_draft(json.dumps(payload, ensure_ascii=False)))

        self.assertTrue(validation["passed"])
        self.assertEqual(session.validated_plan.days[0].meals[0].poi_id, "CHROMA-MEAL-1")

    def test_preloaded_evidence_runs_the_draft_in_one_model_call(self) -> None:
        """完整三类证据已齐备时，不应再让模型串行调用 search_poi。"""
        payload = valid_plan()
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        meal_records = {
            meal["poi_id"]: {
                "poi_id": meal["poi_id"],
                "name": meal["name"],
                "address": meal["address"],
                "location": (
                    f'{meal["location"]["longitude"]},'
                    f'{meal["location"]["latitude"]}'
                ),
                "cost": str(meal["estimated_cost"]),
            }
            for meal in payload["days"][0]["meals"]
        }
        session.evidence_ids["meal"] = set(meal_records)
        session.evidence_records["meal"] = meal_records
        session.evidence_preloaded = True
        session.preloaded_evidence = json.dumps(
            {"poi_evidence": {"meal": list(meal_records.values())}},
            ensure_ascii=False,
        )
        llm = FakeLLM([
            "Action: validate_draft[" + json.dumps(payload, ensure_ascii=False) + "]",
        ])

        result = ValidatedPlanningReActAgent(llm=llm, session=session).run("规划一天行程")

        self.assertEqual(llm.calls, 1)
        self.assertNotIn("search_poi:", llm.prompts[0])
        self.assertIn("已准备好的 POI 证据", llm.prompts[0])
        self.assertEqual(TripPlan.model_validate_json(result).city, "深圳坪山")

    def test_prepare_required_evidence_compacts_all_three_poi_groups(self) -> None:
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
            cached_pois=[
                {
                    "poi_group": purpose,
                    "poi_id": f"{purpose}-{index}",
                    "name": f"{purpose} 候选{index}",
                    "address": "坪山测试路1号",
                    "longitude": 114.4,
                    "latitude": 22.7,
                    "adcode": "440310",
                    "type": "测试类型",
                    "cost": "36",
                    "distance": 0.1,
                }
                for purpose in ("meal", "attraction", "hotel")
                for index in (range(1, 4) if purpose == "meal" else range(1, 2))
            ],
        )

        self.assertTrue(PlanningToolset(session).prepare_required_evidence())
        evidence = json.loads(session.preloaded_evidence)["poi_evidence"]

        self.assertTrue(session.evidence_preloaded)
        self.assertEqual(set(evidence), {"meal", "attraction", "hotel"})
        self.assertEqual(len(evidence["meal"]), 3)
        self.assertEqual(evidence["meal"][0]["cost"], "36")
        self.assertNotIn("distance", evidence["attraction"][0])

    def test_empty_chroma_refills_all_evidence_before_react(self) -> None:
        """空缓存应由后端一次预取补齐，不把三类搜索留给模型逐轮偿还。"""
        request = TripRequest(
            city="广州越秀",
            start_date="2026-07-27",
            end_date="2026-07-29",
            travel_days=3,
            transportation="公共交通",
            accommodation="经济型酒店",
        )
        session = PlanningSession(
            request=request,
            city_center=Location(longitude=113.266835, latitude=23.128537),
            radius_km=25,
            target_adcode="440104",
            amap_city="广州市",
            cached_pois=[],
        )
        calls = []
        persisted = []

        class FakePhotoService:
            def search_pois(self, keywords, city, offset, *, persist):
                calls.append((keywords, city, offset, persist))
                if "餐馆" in keywords or "餐厅" in keywords:
                    return [
                        {
                            "id": f"meal-{index}",
                            "name": f"越秀餐馆{index}",
                            "address": f"越秀路{index}号",
                            "location": f"113.{266000 + index},23.128537",
                            "adcode": "440104",
                            "type": "餐饮服务;中餐厅",
                            "typecode": "050100",
                            "biz_ext": {"cost": "38"},
                        }
                        for index in range(1, 10)
                    ]
                if "景点" in keywords:
                    return [{
                        "id": "attraction-1",
                        "name": "越秀公园",
                        "address": "解放北路988号",
                        "location": "113.264200,23.141600",
                        "adcode": "440104",
                        "type": "风景名胜;公园",
                        "typecode": "110101",
                    }]
                return [{
                    "id": "hotel-1",
                    "name": "越秀经济型酒店",
                    "address": "越秀路1号",
                    "location": "113.267000,23.129000",
                    "adcode": "440104",
                    "type": "住宿服务;宾馆酒店",
                    "typecode": "100100",
                }]

        class FakeStore:
            def upsert_pois(self, pois, city):
                persisted.extend((poi["id"], city) for poi in pois)

        with (
            patch(
                "backend.app.services.planning_service.get_amap_photo_service",
                return_value=FakePhotoService(),
            ),
            patch(
                "backend.app.services.planning_service.get_poi_vector_store",
                return_value=FakeStore(),
            ),
        ):
            prepared = PlanningToolset(session).prepare_required_evidence()

        self.assertTrue(prepared)
        self.assertTrue(session.evidence_preloaded)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(city == "广州市" and persist is False for _, city, _, persist in calls))
        meal_call = next(call for call in calls if "餐馆" in call[0])
        self.assertGreaterEqual(meal_call[2], 18)
        self.assertEqual(len(persisted), 11)

    def test_out_of_city_candidates_are_not_evidence_or_cache(self) -> None:
        session = PlanningSession(
            request=TripRequest(
                city="广州越秀",
                start_date="2026-07-27",
                end_date="2026-07-27",
                travel_days=1,
                transportation="公共交通",
                accommodation="经济型酒店",
            ),
            city_center=Location(longitude=113.266835, latitude=23.128537),
            radius_km=25,
            target_adcode="440104",
            amap_city="广州市",
            cached_pois=[{
                "poi_group": "meal",
                "poi_id": "wrong-cache",
                "name": "外地餐馆",
                "address": "河北省",
                "longitude": 116.8,
                "latitude": 38.5,
                "adcode": "130900",
                "distance": 0.1,
            }],
        )
        persisted = []

        class FakePhotoService:
            def search_pois(self, *_args, **_kwargs):
                return [
                    {
                        "id": "gz-meal",
                        "name": "越秀餐馆",
                        "address": "越秀路1号",
                        "location": "113.267000,23.129000",
                        "adcode": "440104",
                        "type": "餐饮服务;中餐厅",
                        "typecode": "050100",
                    },
                    {
                        "id": "wrong-amap",
                        "name": "五台山餐馆",
                        "address": "山西省",
                        "location": "113.590117,38.967437",
                        "adcode": "140922",
                        "type": "餐饮服务;中餐厅",
                        "typecode": "050100",
                    },
                ]

        class FakeStore:
            def upsert_pois(self, pois, city):
                persisted.extend((poi["id"], city) for poi in pois)

        with (
            patch(
                "backend.app.services.planning_service.get_amap_photo_service",
                return_value=FakePhotoService(),
            ),
            patch(
                "backend.app.services.planning_service.get_poi_vector_store",
                return_value=FakeStore(),
            ),
        ):
            result = json.loads(PlanningToolset(session).search_poi(json.dumps({
                "purpose": "meal",
                "query": "广州越秀平价餐馆",
                "category": "餐饮服务",
            }, ensure_ascii=False)))

        self.assertEqual(result["source"], "amap")
        self.assertEqual([item["poi_id"] for item in result["candidates"]], ["gz-meal"])
        self.assertEqual(persisted, [("gz-meal", "广州市")])
        self.assertNotIn("wrong-cache", session.evidence_ids["meal"])

    def test_validator_rejects_duplicate_meal_poi_and_long_route_leg(self) -> None:
        payload = valid_plan()
        meals = payload["days"][0]["meals"]
        meals[1].update({
            "name": meals[0]["name"],
            "address": meals[0]["address"],
            "location": meals[0]["location"],
            "poi_id": meals[0]["poi_id"],
        })
        meals[0]["location"] = {"longitude": 114.300, "latitude": 22.700}
        plan = TripPlan.model_validate(payload)

        issues = collect_trip_plan_issues(plan, trip_request())
        codes = {issue.code for issue in issues}

        self.assertIn("MEAL_POI_DUPLICATE", codes)
        self.assertIn("ROUTE_LEG_TOO_LONG", codes)

    def test_validator_requires_hotel_as_daily_route_anchor(self) -> None:
        payload = valid_plan()
        payload["days"][0]["hotel"] = None

        issues = collect_trip_plan_issues(TripPlan.model_validate(payload), trip_request())

        self.assertIn("HOTEL_MISSING", {issue.code for issue in issues})

    def test_invalid_model_output_becomes_observation_and_recovers(self) -> None:
        plan_json = json.dumps(valid_plan(), ensure_ascii=False, separators=(",", ":"))
        llm = FakeLLM([
            "我已经准备好计划了",
            f"Thought: 按格式提交 Draft 校验\nAction: validate_draft[{plan_json}]",
            "Thought: Validator 已通过\nAction: Finish[已通过校验]",
        ])
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}

        agent = ValidatedPlanningReActAgent(llm=llm, session=session)
        result = agent.run("规划一天行程")

        self.assertEqual(TripPlan.model_validate_json(result).city, "深圳坪山")
        self.assertTrue(any("Invalid response" in item for item in agent.current_history))

    def test_multiline_draft_action_reaches_validator(self) -> None:
        """模型将 JSON 格式化为多行时，不能丢掉后续餐饮节点。"""
        plan_json = json.dumps(valid_plan(), ensure_ascii=False, indent=2)
        llm = FakeLLM([
            f"Thought: 提交完整 Draft\nAction: validate_draft[{plan_json}]",
            "Thought: Validator 已通过\nAction: Finish[已通过校验]",
        ])
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}

        result = ValidatedPlanningReActAgent(llm=llm, session=session).run("规划一天行程")

        self.assertEqual(len(TripPlan.model_validate_json(result).days[0].meals), 3)

    def test_direct_trip_plan_json_is_validated_when_action_is_omitted(self) -> None:
        """模型漏写 Action 标签时，完整 Draft 仍须经过 Validator 后交付。"""
        plan_json = json.dumps(valid_plan(), ensure_ascii=False)
        llm = FakeLLM([
            f"Thought: 已根据餐饮候选完成安排\n{plan_json}",
            "Thought: Validator 已通过\nAction: Finish[已通过校验]",
        ])
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}

        result = ValidatedPlanningReActAgent(llm=llm, session=session).run("规划一天行程")

        self.assertEqual(len(TripPlan.model_validate_json(result).days[0].meals), 3)

    def test_validator_normalises_real_poi_draft_shapes(self) -> None:
        """真实工具结果的坐标字符串、中文餐次和酒店对象都能进入交付计划。"""
        payload = valid_plan()
        day = payload["days"][0]
        day["accommodation"] = {
            "name": "海友酒店(深圳坪山火车站店)",
            "address": "龙坪路4039号",
            "location": "114.403176,22.700284",
            "type": "经济型酒店",
            "poi_id": "HOTEL1",
        }
        day["hotel"] = None
        day["attractions"][0]["location"] = "114.399831,22.700708"
        day["attractions"][0]["visit_duration"] = "2小时"
        for index, meal in enumerate(day["meals"]):
            meal["type"] = ("早餐", "午餐", "晚餐")[index]
            meal["location"] = f"114.40{index + 1},22.700000"
            meal["estimated_cost"] = f"{36 + index}.0元"

        session = PlanningSession(
            request=trip_request(), city_center=None, radius_km=30, target_adcode=None, amap_city="深圳"
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}
        session.evidence_records["meal"] = {
            meal["poi_id"]: {
                "name": meal["name"], "address": meal["address"], "location": meal["location"],
            }
            for meal in day["meals"]
        }

        result = json.loads(PlanningToolset(session).validate_draft(json.dumps(payload, ensure_ascii=False)))

        self.assertTrue(result["passed"])
        self.assertEqual(session.validated_plan.days[0].meals[0].type, "breakfast")
        self.assertEqual(session.validated_plan.days[0].hotel.location.longitude, 114.403176)

    def test_log_keeps_full_draft_and_delivered_plan(self) -> None:
        plan_json = json.dumps(valid_plan(), ensure_ascii=False, indent=2)
        llm = FakeLLM([
            f"Thought: 提交完整 Draft\nAction: validate_draft[{plan_json}]",
            "Thought: Validator 已通过\nAction: Finish[已通过校验]",
        ])
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}
        ValidatedPlanningReActAgent(llm=llm, session=session).run("规划一天行程")

        draft_event = next(fields for event, fields in self.events if event == "react_step")
        completed = next(fields for event, fields in self.events if event == "run_end")
        self.assertIn('"meals"', draft_event["tool_input_details"])
        self.assertEqual(len(completed["delivered_plan"]["days"][0]["meals"]), 3)

    def test_premature_finish_is_rejected_until_validator_passes(self) -> None:
        plan_json = json.dumps(valid_plan(), ensure_ascii=False, separators=(",", ":"))
        llm = FakeLLM([
            "Thought: 我认为完成了\nAction: Finish[完成]",
            f"Thought: 需要先校验完整计划\nAction: validate_draft[{plan_json}]",
            "Thought: Validator 已通过\nAction: Finish[已通过校验]",
        ])
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}

        agent = ValidatedPlanningReActAgent(llm=llm, session=session)
        result = agent.run("规划一天行程")

        self.assertEqual(TripPlan.model_validate_json(result).city, "深圳坪山")
        self.assertTrue(any("PREMATURE_FINISH" in item for item in agent.current_history))

    def test_validator_reports_missing_real_restaurant_facts(self) -> None:
        payload = valid_plan()
        payload["days"][0]["meals"][1] = {
            "type": "lunch",
            "name": "第1天午餐",
            "description": "午餐推荐",
        }
        plan = TripPlan.model_validate(payload)

        issues = collect_trip_plan_issues(plan, trip_request())
        codes = {issue.code for issue in issues}

        self.assertTrue({"MEAL_POI_MISSING", "MEAL_ADDRESS_MISSING", "MEAL_PRICE_MISSING"} <= codes)

    def test_validator_rejects_meal_that_does_not_match_poi_evidence(self) -> None:
        session = PlanningSession(
            request=trip_request(),
            city_center=Location(longitude=114.4, latitude=22.7),
            radius_km=25,
            target_adcode="440310",
            amap_city="深圳",
        )
        session.evidence_ids["meal"] = {"POI1", "POI2", "POI3"}
        session.evidence_records["meal"] = {
            "POI1": {
                "poi_id": "POI1", "name": "真实早餐店", "address": "坪山区真实路1号",
                "location": "114.401,22.7",
            },
        }

        result = json.loads(PlanningToolset(session).validate_draft(
            json.dumps(valid_plan(), ensure_ascii=False)
        ))

        self.assertFalse(result["passed"])
        self.assertIn(
            "MEAL_POI_FACT_MISMATCH",
            {issue["code"] for issue in result["issues"]},
        )


if __name__ == "__main__":
    from test._output import run_unittest
    run_unittest("验证 ReAct 工具调用、草案解析和 Validator 闸门。")
