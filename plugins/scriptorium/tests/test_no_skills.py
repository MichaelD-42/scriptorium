"""The plugin registers no Claude Code skills (AGENTS.md): a SKILL.md would
be listed in every session with the plugin enabled."""

from conftest import PLUGIN_ROOT


def test_no_skill_files():
    # skills/ is the default scan; a SKILL.md at the root loads the plugin as one skill.
    assert not (PLUGIN_ROOT / "skills").exists()
    assert not (PLUGIN_ROOT / "SKILL.md").exists()
    assert list((PLUGIN_ROOT / "tools").rglob("SKILL.md")) == []


def test_agents_preload_no_skills():
    for agent in (PLUGIN_ROOT / "agents").glob("*.md"):
        frontmatter = agent.read_text(encoding="utf-8").split("---")[1]
        assert "skills:" not in frontmatter, agent.name
