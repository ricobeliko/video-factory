# Video Factory V2 - Procedimento deterministico para recriar banco sintetico DEV_V2
# Gerado deterministicamente para transporte entre ambientes DEV.
import os
import sqlite3
import argparse

SQL_DUMP = """
BEGIN TRANSACTION;
CREATE TABLE autopilot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
INSERT INTO "autopilot_settings" VALUES('autonomous_target_ready_stock:profile-bfdb5411b640','4');
INSERT INTO "autopilot_settings" VALUES('autonomous_target_ready_stock:dev_test_curiosidades','4');
INSERT INTO "autopilot_settings" VALUES('autonomous_max_generations_24h:dev_test_curiosidades','4');
INSERT INTO "autopilot_settings" VALUES('autonomous_mode_enabled:dev_test_curiosidades','False');
INSERT INTO "autopilot_settings" VALUES('autonomous_state:dev_test_curiosidades','disabled');
INSERT INTO "autopilot_settings" VALUES('autonomous_message:dev_test_curiosidades','Produção autônoma do perfil ''dev_test_curiosidades'' desativada pelo operador');
INSERT INTO "autopilot_settings" VALUES('autonomous_target_ready_stock:dev_test_quiz_biblico','5');
INSERT INTO "autopilot_settings" VALUES('autonomous_max_generations_24h:dev_test_quiz_biblico','5');
INSERT INTO "autopilot_settings" VALUES('autonomous_mode_enabled:dev_test_quiz_biblico','False');
INSERT INTO "autopilot_settings" VALUES('autonomous_state:dev_test_quiz_biblico','disabled');
INSERT INTO "autopilot_settings" VALUES('autonomous_message:dev_test_quiz_biblico','Produção autônoma do perfil ''dev_test_quiz_biblico'' desativada pelo operador');
INSERT INTO "autopilot_settings" VALUES('autonomous_target_ready_stock:dev_test_misterios_papel','3');
INSERT INTO "autopilot_settings" VALUES('autonomous_max_generations_24h:dev_test_misterios_papel','3');
INSERT INTO "autopilot_settings" VALUES('autonomous_mode_enabled:dev_test_misterios_papel','False');
INSERT INTO "autopilot_settings" VALUES('autonomous_state:dev_test_misterios_papel','disabled');
INSERT INTO "autopilot_settings" VALUES('autonomous_message:dev_test_misterios_papel','Produção autônoma do perfil ''dev_test_misterios_papel'' desativada pelo operador');
CREATE TABLE content_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                niche TEXT,
                language TEXT,
                region TEXT,
                default_preset TEXT,
                growth_mode TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
INSERT INTO "content_profiles" VALUES('dev_test_curiosidades','Curiosidades do Mundo','curiosidades-do-mundo','Curiosidades e Fatos','pt-BR','BR','cross_platform','warmup',1,'{"schema_version":1,"editorial":{"topic_brief":null,"content_style":null,"video_format":"traditional","closing_type":null,"num_questions":null},"voice":{"voice_name":"pt-BR-AntonioNeural","voice_rate":null,"voice_volume":null},"visual":{"visual_director_enabled":null,"flow_enabled":null,"flow_scene_count":null,"stock_fallback_enabled":null,"visual_style_brief":null},"subtitle":{"position":null,"font_size":null},"automation":{"autonomous_enabled":null,"target_ready_stock":4,"posts_per_day":null,"max_generations_24h":4,"max_attempts_24h":null},"music":{"enabled":false,"mode":"auto","volume":0.2,"default_mood":"neutral"},"schedule":{"publish_start_hour":10,"publish_end_hour":22,"timezone":"America/Sao_Paulo","min_interval_hours":2,"posts_per_day":1}}','2026-10-18T17:02:51.192413+00:00','2026-10-18T17:12:41.537600+00:00');
INSERT INTO "content_profiles" VALUES('dev_test_quiz_biblico','Quiz Bíblico Sagrado','quiz-biblico-sagrado','Quiz Bíblico e Fé','pt-BR','BR','cross_platform','warmup',1,'{"schema_version":1,"editorial":{"topic_brief":null,"content_style":null,"video_format":"quiz_dilemma","closing_type":null,"num_questions":null},"voice":{"voice_name":"pt-BR-FranciscaNeural","voice_rate":null,"voice_volume":null},"visual":{"visual_director_enabled":null,"flow_enabled":null,"flow_scene_count":null,"stock_fallback_enabled":null,"visual_style_brief":null},"subtitle":{"position":null,"font_size":null},"automation":{"autonomous_enabled":null,"target_ready_stock":5,"posts_per_day":null,"max_generations_24h":5,"max_attempts_24h":null},"music":{"enabled":false,"mode":"auto","volume":0.2,"default_mood":"neutral"},"schedule":{"publish_start_hour":10,"publish_end_hour":22,"timezone":"America/Sao_Paulo","min_interval_hours":2,"posts_per_day":1}}','2026-10-18T17:02:51.784559+00:00','2026-10-18T17:02:51.983456+00:00');
INSERT INTO "content_profiles" VALUES('dev_test_misterios_papel','Mistérios no Papel','misterios-no-papel','Mistérios e Enigmas','pt-BR','BR','cross_platform','warmup',1,'{"schema_version":1,"editorial":{"topic_brief":null,"content_style":null,"video_format":"quiz_paper","closing_type":null,"num_questions":null},"voice":{"voice_name":"pt-BR-AntonioNeural","voice_rate":null,"voice_volume":null},"visual":{"visual_director_enabled":null,"flow_enabled":null,"flow_scene_count":null,"stock_fallback_enabled":null,"visual_style_brief":null},"subtitle":{"position":null,"font_size":null},"automation":{"autonomous_enabled":null,"target_ready_stock":3,"posts_per_day":null,"max_generations_24h":3,"max_attempts_24h":null},"music":{"enabled":false,"mode":"auto","volume":0.2,"default_mood":"neutral"},"schedule":{"publish_start_hour":10,"publish_end_hour":22,"timezone":"America/Sao_Paulo","min_interval_hours":2,"posts_per_day":1}}','2026-10-18T17:02:52.353333+00:00','2026-10-18T17:02:52.534487+00:00');
CREATE TABLE content_quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                trend_id TEXT,
                topic TEXT NOT NULL,
                niche TEXT,
                preset TEXT,
                narrative_structure TEXT,
                hook_text TEXT,
                quality_score REAL NOT NULL,
                quality_label TEXT NOT NULL,
                hook_score REAL,
                originality_score REAL,
                trend_score REAL,
                relevance_score REAL,
                source_confidence_score REAL,
                repetition_score REAL,
                narrative_fit_score REAL,
                duration_fit_score REAL,
                historical_performance_score REAL,
                visual_match_score REAL,
                reasons_json TEXT,
                created_at TEXT NOT NULL
            );
INSERT INTO "content_quality_scores" VALUES(1,'task_dev_test_curiosidades_01',NULL,'Curiosidades #1',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(2,'task_dev_test_curiosidades_02',NULL,'Curiosidades #2',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(3,'task_dev_test_curiosidades_03',NULL,'Curiosidades #3',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(4,'task_dev_test_curiosidades_04',NULL,'Curiosidades #4',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(5,'task_dev_test_quiz_biblico_01',NULL,'Quiz Bíblico #1',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(6,'task_dev_test_quiz_biblico_02',NULL,'Quiz Bíblico #2',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(7,'task_dev_test_quiz_biblico_03',NULL,'Quiz Bíblico #3',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(8,'task_dev_test_quiz_biblico_04',NULL,'Quiz Bíblico #4',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(9,'task_dev_test_quiz_biblico_05',NULL,'Quiz Bíblico #5',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(10,'task_dev_test_misterios_papel_01',NULL,'Mistérios Papel #1',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(11,'task_dev_test_misterios_papel_02',NULL,'Mistérios Papel #2',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "content_quality_scores" VALUES(12,'task_dev_test_misterios_papel_03',NULL,'Mistérios Papel #3',NULL,NULL,NULL,NULL,85.5,'STRONG',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
CREATE TABLE instance_locks (
                lock_key TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                hostname TEXT NOT NULL,
                pid INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL
            );
INSERT INTO "instance_locks" VALUES('PRIMARY_FACTORY','2d333076-579f-4dcf-a6ea-73573469e87f','VIDEO-FACTORY-PROD','DESKTOP-O2RJC7S',4656,'2026-10-18T17:12:01.341689+00:00','2026-10-18T17:41:42.658971+00:00','PRIMARY','ACTIVE');
CREATE TABLE monetization_safety (
                task_id TEXT PRIMARY KEY,
                topic TEXT,
                preset TEXT NOT NULL,
                narrative_structure TEXT,
                word_count INTEGER,
                estimated_duration REAL,
                actual_duration REAL,
                safety_status TEXT NOT NULL,
                safety_reasons TEXT,
                hook_text TEXT,
                cta_text TEXT,
                checked_at TEXT NOT NULL
            );
INSERT INTO "monetization_safety" VALUES('task_dev_test_curiosidades_01','Curiosidades #1','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_curiosidades_02','Curiosidades #2','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_curiosidades_03','Curiosidades #3','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_curiosidades_04','Curiosidades #4','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_quiz_biblico_01','Quiz Bíblico #1','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_quiz_biblico_02','Quiz Bíblico #2','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_quiz_biblico_03','Quiz Bíblico #3','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_quiz_biblico_04','Quiz Bíblico #4','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_quiz_biblico_05','Quiz Bíblico #5','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_misterios_papel_01','Mistérios Papel #1','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_misterios_papel_02','Mistérios Papel #2','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
INSERT INTO "monetization_safety" VALUES('task_dev_test_misterios_papel_03','Mistérios Papel #3','cross_platform','hook_body_cta',120,58.0,59.5,'PASS',NULL,NULL,NULL,'2026-10-18T17:02:52.853301+00:00');
CREATE TABLE operational_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                component TEXT NOT NULL,
                severity TEXT NOT NULL,
                event_type TEXT NOT NULL,
                task_id TEXT,
                message TEXT NOT NULL,
                metadata_json TEXT
            );
INSERT INTO "operational_events" VALUES(1,'2026-10-18T15:17:58.919637+00:00','InstanceLock','INFO','INSTANCE_STOPPED',NULL,'Nó primário ''VIDEO-FACTORY-PROD'' (PID 14560) liberou o lock de instância.',NULL);
INSERT INTO "operational_events" VALUES(2,'2026-10-18T15:24:58.098460+00:00','InstanceLock','INFO','INSTANCE_PRIMARY_ACQUIRED',NULL,'Nó primário ''VIDEO-FACTORY-PROD'' (PID 2240) assumiu o controle da fábrica.','{"node_id": "3c79d80d-f4f1-49e1-8943-9651ac549cbd", "hostname": "DESKTOP-O2RJC7S", "pid": 2240}');
INSERT INTO "operational_events" VALUES(3,'2026-10-18T16:53:23.693623+00:00','InstanceLock','INFO','INSTANCE_VIEW_ONLY_STARTED',NULL,'Instância iniciada em modo SECONDARY_VIEW_ONLY (PID 2424). PRIMARY ativo no nó ''VIDEO-FACTORY-PROD'' (PID 2240).','{"primary_node_id": "3c79d80d-f4f1-49e1-8943-9651ac549cbd", "primary_hostname": "DESKTOP-O2RJC7S", "primary_pid": 2240}');
INSERT INTO "operational_events" VALUES(4,'2026-10-18T17:02:51.635950+00:00','autonomous_production','INFO','profile_autonomous_mode_toggled',NULL,'Produção autônoma do perfil ''dev_test_curiosidades'' desativada pelo operador','{"profile_id": "dev_test_curiosidades", "enabled": false}');
INSERT INTO "operational_events" VALUES(5,'2026-10-18T17:02:52.236895+00:00','autonomous_production','INFO','profile_autonomous_mode_toggled',NULL,'Produção autônoma do perfil ''dev_test_quiz_biblico'' desativada pelo operador','{"profile_id": "dev_test_quiz_biblico", "enabled": false}');
INSERT INTO "operational_events" VALUES(6,'2026-10-18T17:02:52.735498+00:00','autonomous_production','INFO','profile_autonomous_mode_toggled',NULL,'Produção autônoma do perfil ''dev_test_misterios_papel'' desativada pelo operador','{"profile_id": "dev_test_misterios_papel", "enabled": false}');
INSERT INTO "operational_events" VALUES(7,'2026-10-18T17:12:01.510731+00:00','InstanceLock','WARNING','INSTANCE_HEARTBEAT_STALE',NULL,'Lock da instância anterior identificado como stale (local_pid_dead (PID 2240 não existe mais no host DESKTOP-O2RJC7S)). Nó anterior: 3c79d80d','{"stale_reason": "local_pid_dead (PID 2240 n\u00e3o existe mais no host DESKTOP-O2RJC7S)", "previous_node": "3c79d80d-f4f1-49e1-8943-9651ac549cbd"}');
INSERT INTO "operational_events" VALUES(8,'2026-10-18T17:12:01.732476+00:00','InstanceLock','WARNING','INSTANCE_TAKEOVER',NULL,'Nó ''VIDEO-FACTORY-PROD'' (PID 4656) executou takeover atômico e assumiu como PRIMARY.','{"node_id": "2d333076-579f-4dcf-a6ea-73573469e87f", "hostname": "DESKTOP-O2RJC7S", "pid": 4656}');
CREATE TABLE operator_review_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                action TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                note TEXT,
                status TEXT NOT NULL,
                result_json TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                processed_at TEXT,
                processed_by_node TEXT
            );
CREATE TABLE operator_video_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT UNIQUE NOT NULL,
                decision TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                note TEXT,
                original_score REAL,
                recalculated_score REAL,
                approved_below_threshold INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata_json TEXT
            );
CREATE TABLE publication_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                published_at TEXT NOT NULL,
                status TEXT NOT NULL,
                external_id TEXT,
                error_code TEXT,
                provider_request_id TEXT,
                profile_id TEXT,
                channel_id TEXT,
                external_url TEXT,
                privacy_status TEXT
            );
INSERT INTO "publication_events" VALUES(1,'task_dev_test_curiosidades_pub01','youtube','2026-10-17T17:02:52.931563+00:00','success','yt_pub_sim_101',NULL,NULL,'dev_test_curiosidades','ch_dev_yt_01','https://youtube.com/shorts/sim101',NULL);
INSERT INTO "publication_events" VALUES(2,'task_dev_test_curiosidades_pub01','tiktok','2026-10-17T17:02:52.931563+00:00','success','tk_pub_sim_201',NULL,NULL,'dev_test_curiosidades','ch_dev_tk_01','https://tiktok.com/@curiosidades/video/201',NULL);
INSERT INTO "publication_events" VALUES(3,'task_dev_test_quiz_biblico_pub01','youtube','2026-10-16T17:02:52.931563+00:00','success','yt_pub_sim_102',NULL,NULL,'dev_test_quiz_biblico','ch_dev_yt_02','https://youtube.com/shorts/sim102',NULL);
CREATE TABLE publishing_channels (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                display_name TEXT NOT NULL,
                external_profile_name TEXT,
                external_account_id TEXT,
                project_id TEXT,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (profile_id) REFERENCES content_profiles(id) ON DELETE CASCADE
            );
INSERT INTO "publishing_channels" VALUES('ch_dev_yt_01','dev_test_curiosidades','youtube','Curiosidades do Mundo (YouTube)',NULL,'dev_sim_yt_01',NULL,1,'2026-10-18T17:02:51.681478+00:00','2026-10-18T17:02:51.681478+00:00');
INSERT INTO "publishing_channels" VALUES('ch_dev_tk_01','dev_test_curiosidades','tiktok','Curiosidades do Mundo (TikTok)',NULL,'dev_sim_tk_01',NULL,1,'2026-10-18T17:02:51.738711+00:00','2026-10-18T17:02:51.738711+00:00');
INSERT INTO "publishing_channels" VALUES('ch_dev_yt_02','dev_test_quiz_biblico','youtube','Quiz Bíblico Sagrado (YouTube)',NULL,'dev_sim_yt_02',NULL,1,'2026-10-18T17:02:52.282541+00:00','2026-10-18T17:02:52.282541+00:00');
INSERT INTO "publishing_channels" VALUES('ch_dev_yt_03','dev_test_misterios_papel','youtube','Mistérios no Papel (YouTube)',NULL,'dev_sim_yt_03',NULL,1,'2026-10-18T17:02:52.783603+00:00','2026-10-18T17:02:52.783603+00:00');
INSERT INTO "publishing_channels" VALUES('ch_dev_tk_02','dev_test_misterios_papel','tiktok','Mistérios no Papel (TikTok)',NULL,'dev_sim_tk_02',NULL,1,'2026-10-18T17:02:52.826808+00:00','2026-10-18T17:02:52.826808+00:00');
CREATE TABLE scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL,
                profile_id TEXT,
                channel_id TEXT,
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                next_attempt_at TEXT
            );
INSERT INTO "scheduled_posts" VALUES(1,'task_dev_test_curiosidades_01','youtube','2026-10-18T23:02:52.931563+00:00','planned','2026-10-18T17:02:52.853301+00:00','dev_test_curiosidades','ch_dev_yt_01',0,NULL,NULL);
INSERT INTO "scheduled_posts" VALUES(2,'task_dev_test_curiosidades_01','tiktok','2026-10-18T23:02:52.931563+00:00','planned','2026-10-18T17:02:52.853301+00:00','dev_test_curiosidades','ch_dev_tk_01',0,NULL,NULL);
INSERT INTO "scheduled_posts" VALUES(3,'task_dev_test_quiz_biblico_01','youtube','2026-10-19T05:02:52.931563+00:00','planned','2026-10-18T17:02:52.853301+00:00','dev_test_quiz_biblico','ch_dev_yt_02',0,NULL,NULL);
INSERT INTO "scheduled_posts" VALUES(4,'task_dev_test_misterios_papel_01','youtube','2026-10-19T11:02:52.931563+00:00','planned','2026-10-18T17:02:52.853301+00:00','dev_test_misterios_papel','ch_dev_yt_03',0,NULL,NULL);
CREATE TABLE task_platforms (
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                PRIMARY KEY (task_id, platform)
            );
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_01','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_01','tiktok');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_02','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_02','tiktok');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_03','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_03','tiktok');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_04','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_curiosidades_04','tiktok');
INSERT INTO "task_platforms" VALUES('task_dev_test_quiz_biblico_01','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_quiz_biblico_02','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_quiz_biblico_03','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_quiz_biblico_04','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_quiz_biblico_05','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_misterios_papel_01','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_misterios_papel_01','tiktok');
INSERT INTO "task_platforms" VALUES('task_dev_test_misterios_papel_02','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_misterios_papel_02','tiktok');
INSERT INTO "task_platforms" VALUES('task_dev_test_misterios_papel_03','youtube');
INSERT INTO "task_platforms" VALUES('task_dev_test_misterios_papel_03','tiktok');
CREATE TABLE task_profiles (
                task_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
INSERT INTO "task_profiles" VALUES('task_dev_test_curiosidades_01','dev_test_curiosidades','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_curiosidades_02','dev_test_curiosidades','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_curiosidades_03','dev_test_curiosidades','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_curiosidades_04','dev_test_curiosidades','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_quiz_biblico_01','dev_test_quiz_biblico','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_quiz_biblico_02','dev_test_quiz_biblico','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_quiz_biblico_03','dev_test_quiz_biblico','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_quiz_biblico_04','dev_test_quiz_biblico','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_quiz_biblico_05','dev_test_quiz_biblico','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_misterios_papel_01','dev_test_misterios_papel','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_misterios_papel_02','dev_test_misterios_papel','2026-10-18T17:02:52.853301+00:00');
INSERT INTO "task_profiles" VALUES('task_dev_test_misterios_papel_03','dev_test_misterios_papel','2026-10-18T17:02:52.853301+00:00');
CREATE UNIQUE INDEX idx_active_schedule_v2
        ON scheduled_posts(task_id, COALESCE(channel_id, ''), platform)
        WHERE status IN ('planned', 'ready', 'published');
CREATE INDEX idx_op_events_ts ON operational_events(timestamp);
CREATE INDEX idx_op_events_comp ON operational_events(component);
CREATE INDEX idx_inst_lock_status ON instance_locks(status);
CREATE INDEX idx_content_profiles_slug ON content_profiles(slug);
CREATE INDEX idx_content_profiles_active ON content_profiles(is_active);
CREATE INDEX idx_pub_channels_profile ON publishing_channels(profile_id);
CREATE INDEX idx_task_profiles_pid ON task_profiles(profile_id);
CREATE INDEX idx_quality_task ON content_quality_scores(task_id);
CREATE INDEX idx_quality_trend ON content_quality_scores(trend_id);
CREATE INDEX idx_quality_created ON content_quality_scores(created_at);
CREATE INDEX idx_op_vid_reviews_task ON operator_video_reviews(task_id);
CREATE INDEX idx_op_vid_reviews_dec ON operator_video_reviews(decision);
CREATE INDEX idx_op_rev_cmd_status ON operator_review_commands(status);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('operational_events',8);
INSERT INTO "sqlite_sequence" VALUES('content_quality_scores',12);
INSERT INTO "sqlite_sequence" VALUES('scheduled_posts',4);
INSERT INTO "sqlite_sequence" VALUES('publication_events',3);
COMMIT;
"""

def init_db(target_db_path: str = None, force: bool = False):
    if not target_db_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        target_db_path = os.path.join(base_dir, 'storage', 'video_factory.db')
    
    os.makedirs(os.path.dirname(target_db_path), exist_ok=True)
    
    if os.path.exists(target_db_path) and not force:
        print(f"[WARN] Banco ja existe em {target_db_path}. Use --force para sobrescrever.")
        return False
        
    if os.path.exists(target_db_path) and force:
        os.remove(target_db_path)
        print(f"[INFO] Banco anterior removido: {target_db_path}")
        
    conn = sqlite3.connect(target_db_path)
    conn.executescript(SQL_DUMP)
    conn.commit()
    conn.close()
    print(f"[SUCCESS] Banco sintetico V2 inicializado com sucesso em: {target_db_path}")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inicializa o banco SQLite sintetico da Video Factory V2")
    parser.add_argument("--path", type=str, default=None, help="Caminho do banco SQLite de destino")
    parser.add_argument("--force", action="store_true", help="Sobrescrever banco existente")
    args = parser.parse_args()
    init_db(args.path, args.force)
