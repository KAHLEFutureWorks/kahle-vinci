def test_harness_module_is_importable_from_eval_paths():
    import kahle_knowledge_harness

    assert kahle_knowledge_harness.SCHEMA_VERSION == "kahle.knowledge-harness.v1"
