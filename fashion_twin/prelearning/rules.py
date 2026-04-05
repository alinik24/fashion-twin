"""User-defined rules engine — hard blocks, score adjustments, preferences.

Rules are evaluated against item metadata before LightFM scoring.
They represent hard constraints (never show polyester, always show Maison Margiela)
or soft preferences (prefer items under £50, downrank fast fashion).

Rule types:
  block        → item is excluded from results entirely
  require      → item must match (whitelist)
  prefer       → positive score delta
  downrank     → negative score delta
  avoid_if     → conditional downrank

Examples:
  block    material  contains  polyester
  block    brand     in        [Shein, Boohoo, Pretty Little Thing]
  prefer   condition eq        new_with_tags
  prefer   brand     in        [Sandro, Maje, Isabel Marant]
  downrank price     gt        200
  require  size      eq        M
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from config import get_settings
from storage import PostgresStore

logger = logging.getLogger(__name__)

# ── Rule operations ───────────────────────────────────────────────────────────
# (field_value, rule_value) → bool
OPERATORS = {
    "eq":          lambda fv, rv: str(fv).lower() == str(rv).lower(),
    "ne":          lambda fv, rv: str(fv).lower() != str(rv).lower(),
    "contains":    lambda fv, rv: rv.lower() in str(fv).lower(),
    "not_contains":lambda fv, rv: rv.lower() not in str(fv).lower(),
    "gt":          lambda fv, rv: float(fv or 0) > float(rv),
    "lt":          lambda fv, rv: float(fv or 0) < float(rv),
    "gte":         lambda fv, rv: float(fv or 0) >= float(rv),
    "lte":         lambda fv, rv: float(fv or 0) <= float(rv),
    "in":          lambda fv, rv: str(fv).lower() in [x.strip().lower() for x in rv.split(",")],
    "not_in":      lambda fv, rv: str(fv).lower() not in [x.strip().lower() for x in rv.split(",")],
    "matches":     lambda fv, rv: bool(re.search(rv, str(fv), re.IGNORECASE)),
}


@dataclass
class Rule:
    rule_type: str       # block | require | prefer | downrank | avoid_if
    field: str           # item field name
    operator: str        # from OPERATORS
    value: str           # comparison value
    reward_delta: float = 0.0
    rule_id: Optional[int] = None

    def matches(self, item: dict) -> bool:
        """Return True if this rule fires for the given item."""
        fv = item.get(self.field)
        if fv is None:
            return False
        op = OPERATORS.get(self.operator)
        if not op:
            return False
        try:
            return op(fv, self.value)
        except Exception:
            return False

    def apply(self, item: dict) -> tuple[bool, float]:
        """
        Apply rule to item.
        Returns (blocked: bool, score_delta: float).
        """
        if not self.matches(item):
            return False, 0.0

        if self.rule_type == "block":
            return True, 0.0
        if self.rule_type == "require":
            # If require fires, item passes; if it doesn't fire, block
            return False, self.reward_delta
        if self.rule_type in ("prefer", "downrank"):
            return False, self.reward_delta
        if self.rule_type == "avoid_if":
            return False, -abs(self.reward_delta)
        return False, 0.0


@dataclass
class RuleApplicationResult:
    blocked: bool = False
    score_delta: float = 0.0
    fired_rules: list[str] = field(default_factory=list)


class RulesEngine:
    """Evaluate a list of rules against items to filter and re-score."""

    def __init__(self, user_id: int = 1) -> None:
        self._user_id = user_id
        self._rules: list[Rule] = []
        self._require_fields: dict[str, list[Rule]] = {}  # field → [require rules]
        self._loaded = False

    def load(self) -> None:
        """Load rules from PostgreSQL."""
        try:
            with PostgresStore() as db:
                db.connect()
                with db._cursor() as cur:
                    cur.execute(
                        """SELECT id, rule_type, field, operator, value, reward_delta
                           FROM user_rules
                           WHERE user_id = %s AND active = TRUE
                           ORDER BY rule_type, id""",
                        (self._user_id,),
                    )
                    rows = cur.fetchall()
            self._rules = [
                Rule(
                    rule_id=r["id"],
                    rule_type=r["rule_type"],
                    field=r["field"],
                    operator=r["operator"],
                    value=r["value"],
                    reward_delta=float(r["reward_delta"] or 0),
                )
                for r in rows
            ]
            # Index require rules by field for fast lookup
            self._require_fields = {}
            for rule in self._rules:
                if rule.rule_type == "require":
                    self._require_fields.setdefault(rule.field, []).append(rule)
            logger.info("Loaded %d rules", len(self._rules))
        except Exception as exc:
            logger.warning("Rules load failed: %s", exc)
        self._loaded = True

    def apply(self, item: dict) -> RuleApplicationResult:
        """Apply all rules to an item. Returns filter+score result."""
        if not self._loaded:
            self.load()

        result = RuleApplicationResult()

        # Check require rules first: if a field has require rules, item must match at least one
        for field_name, require_rules in self._require_fields.items():
            if any(r.matches(item) for r in require_rules):
                pass  # field passes
            else:
                # Item doesn't meet any require rule for this field → block
                result.blocked = True
                result.fired_rules.append(f"require:{field_name}:NOT_MET")
                return result

        for rule in self._rules:
            if rule.rule_type == "require":
                continue  # already handled above
            blocked, delta = rule.apply(item)
            if blocked:
                result.blocked = True
                result.fired_rules.append(f"block:{rule.field}:{rule.value}")
                return result
            if delta != 0.0:
                result.score_delta += delta
                result.fired_rules.append(
                    f"{rule.rule_type}:{rule.field}:{delta:+.1f}"
                )

        return result

    def filter_items(self, items: list[dict]) -> tuple[list[dict], list[dict]]:
        """
        Filter items through rules engine.
        Returns (allowed_items, blocked_items).
        """
        allowed, blocked = [], []
        for item in items:
            r = self.apply(item)
            if r.blocked:
                blocked.append(item)
            else:
                item["_rule_delta"] = r.score_delta
                item["_fired_rules"] = r.fired_rules
                allowed.append(item)
        return allowed, blocked

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add_rule(
        self,
        rule_type: str,
        field: str,
        operator: str,
        value: str,
        reward_delta: float = 0.0,
    ) -> int:
        if operator not in OPERATORS:
            raise ValueError(f"Unknown operator '{operator}'. Valid: {list(OPERATORS)}")
        if rule_type not in ("block", "require", "prefer", "downrank", "avoid_if"):
            raise ValueError(f"Unknown rule_type '{rule_type}'")
        with PostgresStore() as db:
            with db._cursor() as cur:
                cur.execute(
                    """INSERT INTO user_rules (user_id, rule_type, field, operator, value, reward_delta)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (self._user_id, rule_type, field, operator, value, reward_delta),
                )
                rule_id = cur.fetchone()["id"]
        self._loaded = False   # force reload
        logger.info("Added rule #%d: %s %s %s %s", rule_id, rule_type, field, operator, value)
        return rule_id

    def delete_rule(self, rule_id: int) -> None:
        with PostgresStore() as db:
            with db._cursor() as cur:
                cur.execute(
                    "UPDATE user_rules SET active=FALSE WHERE id=%s AND user_id=%s",
                    (rule_id, self._user_id),
                )
        self._loaded = False

    def list_rules(self) -> list[dict]:
        with PostgresStore() as db:
            db.connect()
            with db._cursor() as cur:
                cur.execute(
                    "SELECT * FROM user_rules WHERE user_id=%s AND active=TRUE ORDER BY rule_type,id",
                    (self._user_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ── Preset rule packs ─────────────────────────────────────────────────────

    def apply_preset(self, preset: str) -> None:
        """Apply a named preset rule pack."""
        presets = {
            "sustainable": [
                ("block", "brand", "in", "Shein,ASOS,Boohoo,PrettyLittleThing,Missguided,H&M,Zara", 0),
                ("block", "raw_data.material", "contains", "polyester", 0),
                ("block", "raw_data.material", "contains", "acrylic", 0),
                ("prefer", "condition", "eq", "new_with_tags", 1.5),
            ],
            "luxury_only": [
                ("require", "brand", "in",
                 "Chanel,Louis Vuitton,Hermès,Prada,Gucci,Dior,Bottega Veneta,Celine,Loewe", 0),
                ("prefer", "condition", "in", "new_with_tags,very_good", 2.0),
            ],
            "budget": [
                ("block", "price", "gt", "100", 0),
                ("prefer", "price", "lt", "30", 1.0),
            ],
        }
        rules = presets.get(preset)
        if not rules:
            raise ValueError(f"Unknown preset '{preset}'. Valid: {list(presets)}")
        for rule_type, field, op, value, delta in rules:
            self.add_rule(rule_type, field, op, value, delta)
        logger.info("Applied preset '%s' (%d rules)", preset, len(rules))
