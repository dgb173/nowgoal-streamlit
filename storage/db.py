# storage/db.py
from sqlalchemy import (create_engine, Column, Integer, String, Float, Date, Boolean,
                        MetaData, Table, UniqueConstraint)
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import sqlalchemy as sa
import pandas as pd

DB_PATH = Path("data/ah.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
metadata = MetaData()

matches = Table(
    "matches", metadata,
    Column("match_id", String, primary_key=True),
    Column("league_id", String, index=True),
    Column("season", String),
    Column("match_date", String),
    Column("home", String), Column("away", String),
    Column("ah_line", Float),  # negativo => visitante favorito (tu convención)
    Column("ou_line", Float, nullable=True),
    Column("home_goals", Integer, nullable=True),
    Column("away_goals", Integer, nullable=True),
    Column("shots_home", Integer, nullable=True),
    Column("shots_away", Integer, nullable=True),
    Column("sot_home", Integer, nullable=True),
    Column("sot_away", Integer, nullable=True),
    Column("da_home", Integer, nullable=True),  # dangerous attacks
    Column("da_away", Integer, nullable=True),
    UniqueConstraint("match_id", name="uix_match")
)

features = Table(
    "features", metadata,
    Column("match_id", String, primary_key=True),
    Column("fav_is_away", Boolean),
    Column("ah_abs", Float),
    Column("is_big_spread", Boolean),
    Column("is_quarter", Boolean),
    Column("rare_line_flag", Boolean),
    Column("delta_line_vs_team_median", Float),
    Column("home_scoring_persistence", Float),
    Column("visitor_away_goal_ceiling", Float),
)

predictions = Table(
    "predictions", metadata,
    Column("match_id", String, primary_key=True),
    Column("pred_cover_prob", Float),
    Column("pred_after_rules", Float),
    Column("decision", String),     # PICK_AH / ABSTAIN
    Column("ah_recommendation", String),  # e.g., "VIS -0.25", "HOME +0.5"
    Column("ou_recommendation", String, nullable=True),
    Column("notes", String, nullable=True)
)

results = Table(
    "results", metadata,
    Column("match_id", String, primary_key=True),
    Column("cover_full_or_half", Integer),  # 1/0
    Column("final_score", String)
)

metadata.create_all(engine)

def upsert_matches(df: pd.DataFrame):
    # df con columnas: match_id, league_id, season, match_date, home, away, ah_line, ou_line, home_goals, away_goals, shots_home, shots_away, sot_home, sot_away, da_home, da_away
    with engine.begin() as conn:
        for _, r in df.iterrows():
            stmt = sa.dialects.sqlite.insert(matches).values(**r.to_dict())
            up = stmt.on_conflict_do_update(
                index_elements=["match_id"],
                set_={k: getattr(stmt.excluded, k) for k in r.index if k!="match_id"}
            )
            conn.execute(up)
