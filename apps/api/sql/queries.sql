-- Five read-only queries over the game database (PostgreSQL).
-- Explained one by one in docs/database.md; executed by tests/storage/test_queries.py.
-- `:name` is a bind parameter.

-- name: room_players
-- Who sits where in the room of one game.
SELECT rp.seat, rp.player_id, rp.name, rp.is_bot
FROM rooms AS r
JOIN room_players AS rp ON rp.room_id = r.id
WHERE r.game_id = :game_id
ORDER BY rp.seat;

-- name: game_durations
-- How long each finished game took, newest first.
SELECT g.id AS game_id,
       g.winner,
       g.win_reason,
       g.version AS event_count,
       g.finished_at - g.created_at AS duration
FROM games AS g
WHERE g.finished_at IS NOT NULL
ORDER BY g.finished_at DESC, g.id;

-- name: mission_results
-- The outcome of every completed mission of one game.
SELECT CAST(e.payload ->> 'mission_number' AS integer) AS mission_number,
       e.payload ->> 'outcome' AS outcome,
       CAST(e.payload ->> 'fail_votes' AS integer) AS fail_votes
FROM game_events AS e
WHERE e.game_id = :game_id
  AND e.type = 'mission_completed'
ORDER BY mission_number;

-- name: player_win_rates
-- Win rate of every human nickname over finished games.
WITH dealt AS (
    -- One row per player per finished game: which role they were dealt.
    SELECT g.id AS game_id,
           g.winner,
           role.pair ->> 0 AS player_id,
           role.pair ->> 1 AS role
    FROM games AS g
    JOIN game_events AS e
      ON e.game_id = g.id AND e.type = 'game_started'
    CROSS JOIN LATERAL jsonb_array_elements(e.payload -> 'roles') AS role(pair)
    WHERE g.winner IS NOT NULL
),
sided AS (
    SELECT game_id,
           player_id,
           winner,
           CASE WHEN role IN ('merlin', 'percival', 'loyal_servant') THEN 'good' ELSE 'evil' END
               AS side
    FROM dealt
)
SELECT rp.name,
       count(*) AS games,
       count(*) FILTER (WHERE s.side = s.winner) AS wins,
       round(CAST(count(*) FILTER (WHERE s.side = s.winner) AS numeric) / count(*), 3) AS win_rate
FROM sided AS s
JOIN rooms AS r ON r.game_id = s.game_id
JOIN room_players AS rp ON rp.room_id = r.id AND rp.player_id = s.player_id
WHERE NOT rp.is_bot
GROUP BY rp.name
ORDER BY win_rate DESC, games DESC, rp.name;

-- name: recent_events
-- The last 20 events of one game, newest first.
SELECT e.version, e.type, e.payload, e.created_at
FROM game_events AS e
WHERE e.game_id = :game_id
ORDER BY e.version DESC
LIMIT 20;
