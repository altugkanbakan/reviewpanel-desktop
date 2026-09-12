"""
Tests for the persistent agent-output cache (core.py).

Guards:
  * Key invalidation matrix — any input that determines an output
    (manuscript, model, agent number, KB contents, PROMPT_VERSION) must
    change the key; stale reuse would be silent corruption.
  * Agent 6 keys additionally depend on the upstream outputs (content AND
    order) and the journal profile; previous_outputs is mandatory.
  * save/load round trip, miss on unknown key.
  * Eviction by age and by size (oldest first, newest kept).
  * Best-effort behaviour: an unusable cache directory must never raise.

All cache I/O goes to a per-test temp dir via the autouse isolated_cache
fixture in conftest.py — the real user cache is never touched.
"""

import os
import time

import pytest

import core
from core import (
    cache_evict,
    cache_key,
    cache_load,
    cache_save,
    kb_content_hash,
)

PV = 1  # prompt_version used throughout


def _key(md, kb, **over):
    args = dict(
        manuscript_data=md, agent_num=1, model="qwen2.5:7b", kb=kb,
        prompt_version=PV,
    )
    args.update(over)
    return cache_key(**args)


class TestKeyInvalidation:
    def test_same_inputs_same_key(self, manuscript_data, kb):
        assert _key(manuscript_data, kb) == _key(manuscript_data, kb)

    def test_manuscript_changes_key(self, manuscript_data, kb):
        base = _key(manuscript_data, kb)
        changed = dict(manuscript_data, full_text="entirely different text")
        assert _key(changed, kb) != base

    def test_model_changes_key(self, manuscript_data, kb):
        assert _key(manuscript_data, kb, model="llama3:8b") != _key(
            manuscript_data, kb
        )

    def test_agent_num_changes_key(self, manuscript_data, kb):
        assert _key(manuscript_data, kb, agent_num=2) != _key(
            manuscript_data, kb
        )

    def test_kb_content_changes_key(self, manuscript_data, kb):
        edited = dict(kb, strobe=kb["strobe"] + " — edited")
        assert _key(manuscript_data, edited) != _key(manuscript_data, kb)

    def test_prompt_version_changes_key(self, manuscript_data, kb):
        assert _key(manuscript_data, kb, prompt_version=PV + 1) != _key(
            manuscript_data, kb
        )


class TestAgent6Key:
    OUTS = [f"output of agent {n}" for n in range(1, 6)]

    def _key6(self, md, kb, outs=None, profile=""):
        return cache_key(
            md, 6, "qwen2.5:7b", kb, PV,
            journal_profile_text=profile,
            previous_outputs=self.OUTS if outs is None else outs,
        )

    def test_upstream_output_change_changes_key(self, manuscript_data, kb):
        changed = list(self.OUTS)
        changed[2] = "a different agent 3 output"
        assert self._key6(manuscript_data, kb, changed) != self._key6(
            manuscript_data, kb
        )

    def test_upstream_order_change_changes_key(self, manuscript_data, kb):
        swapped = list(self.OUTS)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        assert self._key6(manuscript_data, kb, swapped) != self._key6(
            manuscript_data, kb
        )

    def test_journal_profile_changes_key(self, manuscript_data, kb):
        assert self._key6(
            manuscript_data, kb, profile="JAMA profile"
        ) != self._key6(manuscript_data, kb)

    def test_missing_previous_outputs_raises(self, manuscript_data, kb):
        with pytest.raises(ValueError):
            cache_key(manuscript_data, 6, "qwen2.5:7b", kb, PV)


class TestRoundTrip:
    def test_save_then_load(self, manuscript_data, kb, isolated_cache):
        key = _key(manuscript_data, kb)
        cache_save(
            key, "agent one report body",
            manuscript_data=manuscript_data, model="qwen2.5:7b",
            agent_num=1, prompt_version=PV,
        )
        assert cache_load(key) == "agent one report body"
        # Files really landed in the isolated temp cache, nowhere else
        assert (isolated_cache / f"{key}.md").exists()
        assert (isolated_cache / f"{key}.json").exists()

    def test_wrong_key_is_a_miss(self, manuscript_data, kb):
        key = _key(manuscript_data, kb)
        cache_save(
            key, "body", manuscript_data=manuscript_data,
            model="qwen2.5:7b", agent_num=1, prompt_version=PV,
        )
        assert cache_load("0" * 64) is None

    def test_load_cached_outputs_roundtrip(self, manuscript_data, kb):
        for n in range(1, 6):
            k = _key(manuscript_data, kb, agent_num=n)
            cache_save(
                k, f"out {n}", manuscript_data=manuscript_data,
                model="qwen2.5:7b", agent_num=n, prompt_version=PV,
            )
        found = core.load_cached_outputs(manuscript_data, "qwen2.5:7b", kb, PV)
        assert found == {n: f"out {n}" for n in range(1, 6)}


class TestEviction:
    def _put(self, root, name, body="x" * 1000, age_days=0.0):
        md = root / f"{name}.md"
        js = root / f"{name}.json"
        md.write_text(body, encoding="utf-8")
        js.write_text("{}", encoding="utf-8")
        if age_days:
            old = time.time() - age_days * 86400
            os.utime(md, (old, old))
            os.utime(js, (old, old))
        return md

    def test_age_limit(self, isolated_cache):
        isolated_cache.mkdir(parents=True)
        old = self._put(isolated_cache, "old", age_days=90)
        fresh = self._put(isolated_cache, "fresh", age_days=1)
        removed = cache_evict(max_age_days=60)
        assert removed == 1
        assert not old.exists()
        assert fresh.exists()

    def test_size_limit_drops_oldest_keeps_newest(self, isolated_cache):
        isolated_cache.mkdir(parents=True)
        oldest = self._put(isolated_cache, "a", body="x" * 2000, age_days=3)
        middle = self._put(isolated_cache, "b", body="x" * 2000, age_days=2)
        newest = self._put(isolated_cache, "c", body="x" * 2000, age_days=1)
        # Keep roughly one entry's worth of bytes
        removed = cache_evict(max_bytes=2500, max_age_days=365)
        assert removed == 2
        assert not oldest.exists()
        assert not middle.exists()
        assert newest.exists()

    def test_missing_root_is_noop(self, isolated_cache):
        assert not isolated_cache.exists()
        assert cache_evict() == 0


class TestBestEffort:
    """An unusable cache location must degrade to a no-op, never raise."""

    def test_unwritable_cache_dir_does_not_raise(
        self, manuscript_data, kb, tmp_path, monkeypatch
    ):
        # Point the cache root AT A FILE: mkdir(), glob() etc. fail there.
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("occupied", encoding="utf-8")
        monkeypatch.setattr(core, "cache_dir", lambda: blocker)

        key = _key(manuscript_data, kb)
        cache_save(  # must swallow the failure
            key, "body", manuscript_data=manuscript_data,
            model="qwen2.5:7b", agent_num=1, prompt_version=PV,
        )
        assert cache_load(key) is None
        assert cache_evict() == 0
        assert core.load_cached_outputs(
            manuscript_data, "qwen2.5:7b", kb, PV
        ) == {}


class TestKbContentHash:
    def test_order_independent(self, kb):
        reversed_kb = dict(reversed(list(kb.items())))
        assert list(reversed_kb) != list(kb)  # insertion order differs
        assert kb_content_hash(reversed_kb) == kb_content_hash(kb)

    def test_content_sensitive(self, kb):
        edited = dict(kb, sampl=kb["sampl"] + "!")
        assert kb_content_hash(edited) != kb_content_hash(kb)
