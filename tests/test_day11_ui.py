from streamlit.testing.v1 import AppTest

from app import service


def _assert_no_ui_exception(app: AppTest) -> None:
    assert not app.exception, [item.value for item in app.exception]


def test_frozen_benchmark_ui_clean_and_ugly_workflows():
    app = AppTest.from_file("app/streamlit_app.py", default_timeout=180)
    app.run(timeout=180)
    _assert_no_ui_exception(app)
    assert app.sidebar.selectbox[0].value == service.DEFAULT_MODE

    app.button[0].click().run(timeout=180)
    _assert_no_ui_exception(app)
    assert [tab.label for tab in app.tabs] == [
        "Results", "Field evidence", "Cost & performance", "Operating modes", "Benchmark"
    ]
    assert len(app.get("download_button")) == 2
    assert any("Final frozen synthetic benchmark" in item.value for item in app.warning)

    ugly = next(item for item in service.list_synthetic_examples()
                if item["doc_id"] == "cms1500_42_0000" and item["tier"] == "ugly")
    app.sidebar.selectbox[1].set_value(ugly).run(timeout=180)
    app.button[0].click().run(timeout=180)
    _assert_no_ui_exception(app)
    assert len(app.get("download_button")) == 2
