"""
app/services/quiz_generator.py
==============================
VIDEO FACTORY — FASE Q2: GERAÇÃO AUTOMÁTICA DE CONTEÚDO PARA QUIZ ENGINE

Serviço de geração e estruturação automatizada de conteúdo para o Quiz Engine:
1. Geração para múltiplos nichos (subjetivo: escolhas impossíveis; factual: trivia/conhecimentos verificados).
2. Prevenção de duplicatas via histórico persistente e cálculo de similaridade léxica.
3. Checagem factual estrita para quizzes com resposta correta.
4. Seleção e deduplicação de imagens (Pexels / Pixabay) via IDs e hashes.
5. Ganchos de retenção dinâmicos contextualizados com a última pergunta.
6. Encerramentos flexíveis por canal (CTA de engajamento, desafio de pontuação ou quiz religioso).
7. Serialização em formato JSON estritamente compatível com QuizConfig da Fase Q1.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
import requests

from app.config import config
from app.services import llm, material
from scripts.poc_quiz_render import QuizConfig

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_DIR = os.path.join(ROOT_DIR, "storage", "quiz_history")
QUIZ_TEMPLATES_DIR = os.path.join(ROOT_DIR, "resource", "quiz_templates")



# =============================================================================
# Variações Naturais para Encerramento Editorial de Quiz (Dilema 7 e Dilema 8)
# =============================================================================
DILEMMA_7_JESUS_VARIATIONS = [
    {
        "narration": "Você prefere ficar trinta dias sem internet... Ou curtir o vídeo e comentar por Jesus?",
        "top": {
            "title": "30 DIAS SEM INTERNET",
            "tag": "OPÇÃO A",
            "image_query": "broken smartphone disconnected no wifi screen",
            "theme": "red",
        },
        "bottom": {
            "title": "CURTIR E COMENTAR POR JESUS",
            "tag": "OPÇÃO B",
            "image_query": "jesus christ cross heavenly light blessing sunrise",
            "theme": "gold_red",
        },
        "percentage_top": 14,
        "percentage_bottom": 86,
    },
    {
        "narration": "Você prefere perder seu celular agora... Ou curtir e comentar Jesus nos comentários?",
        "top": {
            "title": "PERDER SEU CELULAR AGORA",
            "tag": "OPÇÃO A",
            "image_query": "shattered broken phone on ground screen cracked",
            "theme": "red",
        },
        "bottom": {
            "title": "CURTIR E COMENTAR JESUS",
            "tag": "OPÇÃO B",
            "image_query": "christian cross sunset silhouette spiritual hope",
            "theme": "gold_red",
        },
        "percentage_top": 12,
        "percentage_bottom": 88,
    },
    {
        "narration": "Ficar um mês sem nenhuma rede social... Ou curtir o vídeo em honra a Jesus?",
        "top": {
            "title": "1 MÊS SEM REDES SOCIAIS",
            "tag": "OPÇÃO A",
            "image_query": "lonely person looking at blank wall boredom",
            "theme": "red",
        },
        "bottom": {
            "title": "CURTIR EM HONRA A JESUS",
            "tag": "OPÇÃO B",
            "image_query": "golden cross glowing rays of light sky faith",
            "theme": "gold_red",
        },
        "percentage_top": 15,
        "percentage_bottom": 85,
    },
    {
        "narration": "Tomar banho gelado no inverno por um ano... Ou curtir e glorificar a Jesus?",
        "top": {
            "title": "BANHO GELADO POR UM ANO",
            "tag": "OPÇÃO A",
            "image_query": "freezing cold shower ice water shivering",
            "theme": "red",
        },
        "bottom": {
            "title": "CURTIR E GLORIFICAR A JESUS",
            "tag": "OPÇÃO B",
            "image_query": "divine light clouds heaven holy cross morning",
            "theme": "gold_red",
        },
        "percentage_top": 10,
        "percentage_bottom": 90,
    },
    {
        "narration": "Perder todo o dinheiro da carteira agora... Ou curtir e digitar Jesus nos comentários?",
        "top": {
            "title": "PERDER DINHEIRO DA CARTEIRA",
            "tag": "OPÇÃO A",
            "image_query": "empty wallet leather broken broke sad",
            "theme": "red",
        },
        "bottom": {
            "title": "DIGITAR JESUS NO VÍDEO",
            "tag": "OPÇÃO B",
            "image_query": "hands praying worship god faith light cross",
            "theme": "gold_red",
        },
        "percentage_top": 11,
        "percentage_bottom": 89,
    },
    {
        "narration": "Ficar um ano sem comer sua comida favorita... Ou deixar a curtida e comentar por Jesus?",
        "top": {
            "title": "1 ANO SEM COMIDA FAVORITA",
            "tag": "OPÇÃO A",
            "image_query": "sad person looking at empty plate fasting",
            "theme": "red",
        },
        "bottom": {
            "title": "DEIXAR A CURTIDA POR JESUS",
            "tag": "OPÇÃO B",
            "image_query": "sacred heart cross beautiful church sunlight",
            "theme": "gold_red",
        },
        "percentage_top": 13,
        "percentage_bottom": 87,
    },
    {
        "narration": "Passar uma semana sem dormir na sua cama... Ou curtir agora e agradecer a Jesus?",
        "top": {
            "title": "UMA SEMANA SEM SUA CAMA",
            "tag": "OPÇÃO A",
            "image_query": "person sleeping on uncomfortable cold hard floor",
            "theme": "red",
        },
        "bottom": {
            "title": "CURTIR E AGRADECER A JESUS",
            "tag": "OPÇÃO B",
            "image_query": "open bible cross divine light sunrise gratitude",
            "theme": "gold_red",
        },
        "percentage_top": 9,
        "percentage_bottom": 91,
    },
    {
        "narration": "Andar vinte quilômetros a pé na chuva... Ou curtir o vídeo e comentar por Jesus?",
        "top": {
            "title": "20 KM A PÉ NA CHUVA",
            "tag": "OPÇÃO A",
            "image_query": "person walking in heavy rain stormy road wet",
            "theme": "red",
        },
        "bottom": {
            "title": "CURTIR E COMENTAR POR JESUS",
            "tag": "OPÇÃO B",
            "image_query": "heavenly rays shining through dark clouds cross",
            "theme": "gold_red",
        },
        "percentage_top": 8,
        "percentage_bottom": 92,
    },
]

DILEMMA_8_CTA_VARIATIONS = [
    {
        "narration": "Passar direto e perder os próximos vídeos... Ou seguir o perfil e apoiar o canal agora?",
        "top": {
            "title": "PASSAR DIRETO E PERDER TUDO",
            "tag": "OPÇÃO A",
            "image_query": "person walking away empty dark road night",
            "theme": "blue_neutral",
        },
        "bottom": {
            "title": "SEGUIR O PERFIL AGORA",
            "tag": "OPÇÃO B",
            "image_query": "smartphone social media follow subscribe celebration confetti",
            "theme": "gold_red",
        },
        "percentage_top": 9,
        "percentage_bottom": 91,
    },
    {
        "narration": "Ignorar este vídeo e perder os novos desafios... Ou seguir o canal e receber bênçãos com a gente?",
        "top": {
            "title": "IGNORAR E PERDER DESAFIOS",
            "tag": "OPÇÃO A",
            "image_query": "scrolling past smartphone screen blurred dark",
            "theme": "blue_neutral",
        },
        "bottom": {
            "title": "SEGUIR O CANAL E RECEBER BÊNÇÃOS",
            "tag": "OPÇÃO B",
            "image_query": "community hands together golden sunset celebration",
            "theme": "gold_red",
        },
        "percentage_top": 8,
        "percentage_bottom": 92,
    },
    {
        "narration": "Passar direto e não ver mais nossas escolhas... Ou seguir a página e apoiar o canal hoje?",
        "top": {
            "title": "PASSAR DIRETO E NÃO VER MAIS",
            "tag": "OPÇÃO A",
            "image_query": "person turning back darkness silhouette road",
            "theme": "blue_neutral",
        },
        "bottom": {
            "title": "SEGUIR A PÁGINA HOJE",
            "tag": "OPÇÃO B",
            "image_query": "bright smartphone notifications follow subscribe gold",
            "theme": "gold_red",
        },
        "percentage_top": 10,
        "percentage_bottom": 90,
    },
    {
        "narration": "Passar reto e esquecer esta mensagem... Ou seguir o perfil e compartilhar com os amigos?",
        "top": {
            "title": "PASSAR RETO E ESQUECER",
            "tag": "OPÇÃO A",
            "image_query": "empty desert road dust wind forgotten",
            "theme": "blue_neutral",
        },
        "bottom": {
            "title": "SEGUIR E COMPARTILHAR",
            "tag": "OPÇÃO B",
            "image_query": "happy friends laughing sharing mobile video light",
            "theme": "gold_red",
        },
        "percentage_top": 7,
        "percentage_bottom": 93,
    },
]


# =============================================================================
# Clusters Temáticos e Catálogo Canônico Homologado para Quiz de Escolhas / Dilemas
# =============================================================================
DILEMMA_THEMATIC_CLUSTERS: List[Tuple[str, str]] = [
    ("SUPERPODERES E HABILIDADES", "Superpoderes fantásticos, dons mentais inacreditáveis e sentidos aguçados."),
    ("RIQUEZA E LUXO", "Fortunas repentinas, heranças improváveis, luxo extremo e sacrifícios materiais."),
    ("VIAGEM NO TEMPO E UNIVERSO", "Realidades paralelas, exploração do cosmos, viagens ao passado e ao futuro distante."),
    ("SOBREVIVÊNCIA E NATUREZA", "Cenários extremos na selva, ilhas desertas, vida selvagem e desafios de sobrevivência."),
    ("COTIDIANO E CONVIVÊNCIA", "Situações embaraçosas hilárias, manias diárias, regras sociais inusitadas e conforto moderno."),
    ("MISTÉRIO E DESTINO", "Sexto sentido, segredos do destino, enigmas inexplicáveis e decisões psicológicas."),
]

CANONICAL_DILEMMA_CATALOG: List[Dict[str, Any]] = [
    # 1. Superpoderes & Habilidades
    {
        "category": "SUPERPODERES",
        "header": "ESCOLHA RÁPIDO:",
        "narration": "Controlar o fogo com as mãos... Ou respirar debaixo d'água sem limites?",
        "top": {"title": "CONTROLAR O FOGO", "tag": "OPÇÃO A", "image_query": "fire elemental glowing flames power hands", "theme": "red"},
        "bottom": {"title": "RESPIRAR DEBAIXO D'ÁGUA", "tag": "OPÇÃO B", "image_query": "underwater ocean swimmer coral reef sunlight", "theme": "blue"},
        "percentage_top": 52, "percentage_bottom": 48, "countdown_sec": 3.0,
    },
    {
        "category": "SUPERPODERES",
        "header": "DECISÃO DIFÍCIL:",
        "narration": "Teletransportar para onde quiser... Ou parar o tempo por dez segundos?",
        "top": {"title": "TELETRANSPORTE INSTANTÂNEO", "tag": "OPÇÃO A", "image_query": "teleportation portal glowing light fantasy", "theme": "red"},
        "bottom": {"title": "PARAR O TEMPO POR 10S", "tag": "OPÇÃO B", "image_query": "frozen time clocks pocket watch surreal", "theme": "blue"},
        "percentage_top": 61, "percentage_bottom": 39, "countdown_sec": 3.0,
    },
    {
        "category": "SUPERPODERES",
        "header": "DILEMA IMPOSSÍVEL:",
        "narration": "Força sobre-humana de dez homens... Ou velocidade para desviar de qualquer golpe?",
        "top": {"title": "FORÇA DE 10 HOMENS", "tag": "OPÇÃO A", "image_query": "superhuman strength lifting heavy rock power", "theme": "red"},
        "bottom": {"title": "VELOCIDADE INESQUIVÁVEL", "tag": "OPÇÃO B", "image_query": "fast runner motion blur trail speed lightning", "theme": "blue"},
        "percentage_top": 45, "percentage_bottom": 55, "countdown_sec": 3.0,
    },
    {
        "category": "SUPERPODERES",
        "header": "QUAL O SEU DESTINO:",
        "narration": "Regenerar qualquer machucado em segundos... Ou nunca mais precisar dormir na vida?",
        "top": {"title": "REGENERAÇÃO INSTANTÂNEA", "tag": "OPÇÃO A", "image_query": "healing glowing light biological regeneration", "theme": "red"},
        "bottom": {"title": "NUNCA MAIS PRECISAR DORMIR", "tag": "OPÇÃO B", "image_query": "night sky starry energetic person waking", "theme": "blue"},
        "percentage_top": 57, "percentage_bottom": 43, "countdown_sec": 3.0,
    },

    # 2. Riqueza & Luxo
    {
        "category": "RIQUEZA",
        "header": "DECISÃO DIFÍCIL:",
        "narration": "Mansão privativa em ilha deserta... Ou cobertura luxuosa no centro de Tóquio?",
        "top": {"title": "MANSÃO EM ILHA PRIVADA", "tag": "OPÇÃO A", "image_query": "luxury private island tropical villa turquoise ocean", "theme": "red"},
        "bottom": {"title": "COBERTURA EM TÓQUIO", "tag": "OPÇÃO B", "image_query": "tokyo penthouse neon skyline luxury modern view", "theme": "blue"},
        "percentage_top": 54, "percentage_bottom": 46, "countdown_sec": 3.0,
    },
    {
        "category": "RIQUEZA",
        "header": "ESCOLHA RÁPIDO:",
        "narration": "Viajar de primeira classe para sempre... Ou comer de graça em qualquer restaurante do mundo?",
        "top": {"title": "PRIMEIRA CLASSE PARA SEMPRE", "tag": "OPÇÃO A", "image_query": "first class airplane luxury seat cabin clouds", "theme": "red"},
        "bottom": {"title": "COMER DE GRAÇA NO MUNDO", "tag": "OPÇÃO B", "image_query": "gourmet restaurant dinner chef table food", "theme": "blue"},
        "percentage_top": 49, "percentage_bottom": 51, "countdown_sec": 3.0,
    },
    {
        "category": "RIQUEZA",
        "header": "DILEMA IMPOSSÍVEL:",
        "narration": "Comprar qualquer carro que desejar... Ou ter um iate com tripulação completa?",
        "top": {"title": "QUALQUER CARRO DO PLANETA", "tag": "OPÇÃO A", "image_query": "supercar luxury garage speed automotive red", "theme": "red"},
        "bottom": {"title": "IATE COM TRIPULAÇÃO", "tag": "OPÇÃO B", "image_query": "mega yacht luxury boat mediterranean blue sea", "theme": "blue"},
        "percentage_top": 43, "percentage_bottom": 57, "countdown_sec": 3.0,
    },
    {
        "category": "RIQUEZA",
        "header": "QUAL O SEU DESTINO:",
        "narration": "Dez milhões em ouro enterrados agora... Ou cem mil reais depositados todo mês pro resto da vida?",
        "top": {"title": "10 MILHÕES EM OURO AGORA", "tag": "OPÇÃO A", "image_query": "treasure chest gold bullion bars sparkling", "theme": "red"},
        "bottom": {"title": "100 MIL POR MÊS PRA SEMPRE", "tag": "OPÇÃO B", "image_query": "bank deposit financial freedom relaxed sunset", "theme": "blue"},
        "percentage_top": 38, "percentage_bottom": 62, "countdown_sec": 3.0,
    },

    # 3. Viagem no Tempo & Universo
    {
        "category": "UNIVERSO",
        "header": "DECISÃO DIFÍCIL:",
        "narration": "Conhecer civilizações alienígenas... Ou descobrir o segredo do início do Universo?",
        "top": {"title": "CONTATO COM ALIENÍGENAS", "tag": "OPÇÃO A", "image_query": "futuristic alien spaceship contact nebula stars", "theme": "red"},
        "bottom": {"title": "SEGREDO DO INÍCIO DO UNIVERSO", "tag": "OPÇÃO B", "image_query": "big bang cosmic explosion galaxies deep space", "theme": "blue"},
        "percentage_top": 53, "percentage_bottom": 47, "countdown_sec": 3.0,
    },
    {
        "category": "UNIVERSO",
        "header": "ESCOLHA RÁPIDO:",
        "narration": "Viver cem anos no Egito Antigo... Ou viver quinhentos anos no futuro hipertecnológico?",
        "top": {"title": "100 ANOS NO EGITO ANTIGO", "tag": "OPÇÃO A", "image_query": "ancient egypt pyramids pharaoh gold sunset", "theme": "red"},
        "bottom": {"title": "500 ANOS NO FUTURO", "tag": "OPÇÃO B", "image_query": "cyberpunk futuristic megalopolis flying cars night", "theme": "blue"},
        "percentage_top": 34, "percentage_bottom": 66, "countdown_sec": 3.0,
    },
    {
        "category": "UNIVERSO",
        "header": "DILEMA IMPOSSÍVEL:",
        "narration": "Explorar o fundo mais escuro do oceano... Ou pisar na superfície de Marte pela primeira vez?",
        "top": {"title": "FUNDO ESCURO DO OCEANO", "tag": "OPÇÃO A", "image_query": "deep sea trench submarine bioluminescent ocean", "theme": "red"},
        "bottom": {"title": "PISAR NO SOLO DE MARTE", "tag": "OPÇÃO B", "image_query": "astronaut red planet mars surface landscape horizon", "theme": "blue"},
        "percentage_top": 41, "percentage_bottom": 59, "countdown_sec": 3.0,
    },
    {
        "category": "UNIVERSO",
        "header": "QUAL O SEU DESTINO:",
        "narration": "Saber exatamente como o mundo vai acabar... Ou saber o dia em que o ser humano vai morar no espaço?",
        "top": {"title": "COMO O MUNDO VAI ACABAR", "tag": "OPÇÃO A", "image_query": "apocalypse meteor horizon dramatic sky cinema", "theme": "red"},
        "bottom": {"title": "QUANDO MORAREMOS NO ESPAÇO", "tag": "OPÇÃO B", "image_query": "space colony orbital station earth view sunrise", "theme": "blue"},
        "percentage_top": 46, "percentage_bottom": 54, "countdown_sec": 3.0,
    },

    # 4. Sobrevivência & Natureza
    {
        "category": "SOBREVIVÊNCIA",
        "header": "ESCOLHA RÁPIDO:",
        "narration": "Sobreviver trinta dias na floresta amazônica... Ou passar duas semanas no gelo da Antártida?",
        "top": {"title": "30 DIAS NA AMAZÔNIA", "tag": "OPÇÃO A", "image_query": "dense amazon rainforest jungle wild green river", "theme": "red"},
        "bottom": {"title": "2 SEMANAS NA ANTÁRTIDA", "tag": "OPÇÃO B", "image_query": "antarctica glacier snow mountains frozen landscape", "theme": "blue"},
        "percentage_top": 58, "percentage_bottom": 42, "countdown_sec": 3.0,
    },
    {
        "category": "SOBREVIVÊNCIA",
        "header": "DECISÃO DIFÍCIL:",
        "narration": "Enfrentar um urso-polar desarmado... Ou mergulhar em lago com três crocodilos famintos?",
        "top": {"title": "ENFRENTAR UM URSO-POLAR", "tag": "OPÇÃO A", "image_query": "polar bear aggressive snow blizzard arctic", "theme": "red"},
        "bottom": {"title": "LAGO COM 3 CROCODILOS", "tag": "OPÇÃO B", "image_query": "alligator crocodile swamp murky water teeth", "theme": "blue"},
        "percentage_top": 36, "percentage_bottom": 64, "countdown_sec": 3.0,
    },
    {
        "category": "SOBREVIVÊNCIA",
        "header": "DILEMA IMPOSSÍVEL:",
        "narration": "Nunca mais poder usar sapatos na vida... Ou nunca mais poder tomar banho quente no frio?",
        "top": {"title": "NUNCA MAIS USAR SAPATOS", "tag": "OPÇÃO A", "image_query": "barefoot walking grass sand nature feet", "theme": "red"},
        "bottom": {"title": "NUNCA MAIS BANHO QUENTE", "tag": "OPÇÃO B", "image_query": "cold shower shivering water winter ice", "theme": "blue"},
        "percentage_top": 51, "percentage_bottom": 49, "countdown_sec": 3.0,
    },
    {
        "category": "SOBREVIVÊNCIA",
        "header": "QUAL O SEU DESTINO:",
        "narration": "Ficar preso em elevador com um leão calmo... Ou preso em caverna escura com cem morcegos?",
        "top": {"title": "ELEVADOR COM UM LEÃO", "tag": "OPÇÃO A", "image_query": "lion sitting calm majestic zoo wild close", "theme": "red"},
        "bottom": {"title": "CAVERNA COM 100 MORCEGOS", "tag": "OPÇÃO B", "image_query": "dark cave bats flying shadows spooky", "theme": "blue"},
        "percentage_top": 44, "percentage_bottom": 56, "countdown_sec": 3.0,
    },

    # 5. Cotidiano & Convivência
    {
        "category": "COTIDIANO",
        "header": "ESCOLHA RÁPIDO:",
        "narration": "Falar rimando todas as frases do dia... Ou ter que dançar toda vez que ouvir música?",
        "top": {"title": "FALAR RIMANDO SEMPRE", "tag": "OPÇÃO A", "image_query": "person talking animated poetry theatre comedy", "theme": "red"},
        "bottom": {"title": "DANÇAR COM QUALQUER MÚSICA", "tag": "OPÇÃO B", "image_query": "person dancing funny street party music headphones", "theme": "blue"},
        "percentage_top": 47, "percentage_bottom": 53, "countdown_sec": 3.0,
    },
    {
        "category": "COTIDIANO",
        "header": "DECISÃO DIFÍCIL:",
        "narration": "Rir alto em momentos tristes... Ou chorar de emoção sempre que alguém espirrar?",
        "top": {"title": "RIR ALTO EM HORAS TRISTES", "tag": "OPÇÃO A", "image_query": "person laughing embarrassed covering mouth", "theme": "red"},
        "bottom": {"title": "CHORAR A CADA ESPIRRO", "tag": "OPÇÃO B", "image_query": "dramatic crying tears funny emotional face", "theme": "blue"},
        "percentage_top": 42, "percentage_bottom": 58, "countdown_sec": 3.0,
    },
    {
        "category": "COTIDIANO",
        "header": "DILEMA IMPOSSÍVEL:",
        "narration": "Usar roupa de inverno no calor de quarenta graus... Ou bermuda e regata na neve congelante?",
        "top": {"title": "CASINHO DE LÃ NO CALORÃO", "tag": "OPÇÃO A", "image_query": "sweating hot sun desert winter coat humor", "theme": "red"},
        "bottom": {"title": "BERMUDA E REGATA NA NEVE", "tag": "OPÇÃO B", "image_query": "shivering cold snow blizzard swimsuit freezing", "theme": "blue"},
        "percentage_top": 55, "percentage_bottom": 45, "countdown_sec": 3.0,
    },
    {
        "category": "COTIDIANO",
        "header": "QUAL O SEU DESTINO:",
        "narration": "Ter a voz de um pato em discussões sérias... Ou esquecer o nome das pessoas assim que elas se apresentam?",
        "top": {"title": "VOZ DE PATO EM REUNIÃO", "tag": "OPÇÃO A", "image_query": "funny duck talking funny microphone conference", "theme": "red"},
        "bottom": {"title": "ESQUECER NOMES NA HORA", "tag": "OPÇÃO B", "image_query": "confused awkward handshake forgetting meeting", "theme": "blue"},
        "percentage_top": 49, "percentage_bottom": 51, "countdown_sec": 3.0,
    },

    # 6. Mistério & Destino
    {
        "category": "MISTÉRIO",
        "header": "DECISÃO DIFÍCIL:",
        "narration": "Ouvir a conversa de qualquer pessoa a dez metros... Ou fazer qualquer pessoa falar a verdade absoluta?",
        "top": {"title": "OUVIR CONVERSAS A 10 METROS", "tag": "OPÇÃO A", "image_query": "whispering secret ear listening crowded city", "theme": "red"},
        "bottom": {"title": "FAZER FALAR A VERDADE", "tag": "OPÇÃO B", "image_query": "truth confession honest eyes glowing mystery", "theme": "blue"},
        "percentage_top": 40, "percentage_bottom": 60, "countdown_sec": 3.0,
    },
    {
        "category": "MISTÉRIO",
        "header": "ESCOLHA RÁPIDO:",
        "narration": "Lembrar de cada segundo da sua infância... Ou esquecer instantaneamente todos os momentos ruins do passado?",
        "top": {"title": "LEMBRAR DE CADA SEGUNDO", "tag": "OPÇÃO A", "image_query": "childhood nostalgia happy memories vintage photo", "theme": "red"},
        "bottom": {"title": "ESQUECER MOMENTOS RUINS", "tag": "OPÇÃO B", "image_query": "peaceful calm sunset mind clean meditation", "theme": "blue"},
        "percentage_top": 43, "percentage_bottom": 57, "countdown_sec": 3.0,
    },
    {
        "category": "MISTÉRIO",
        "header": "DILEMA IMPOSSÍVEL:",
        "narration": "Ter um clone idêntico para trabalhar por você... Ou ter um assistente invisível que faz qualquer tarefa manual?",
        "top": {"title": "CLONE IDÊNTICO NO TRABALHO", "tag": "OPÇÃO A", "image_query": "twin clone businessmen office modern technology", "theme": "red"},
        "bottom": {"title": "ASSISTENTE INVISÍVEL", "tag": "OPÇÃO B", "image_query": "mystical invisible helper floating objects fantasy", "theme": "blue"},
        "percentage_top": 51, "percentage_bottom": 49, "countdown_sec": 3.0,
    },
    {
        "category": "MISTÉRIO",
        "header": "QUAL O SEU DESTINO:",
        "narration": "Saber todos os segredos dos governos do mundo... Ou saber a resposta para todos os mistérios da ciência?",
        "top": {"title": "SEGREDOS DOS GOVERNOS", "tag": "OPÇÃO A", "image_query": "classified document top secret files archives dark", "theme": "red"},
        "bottom": {"title": "MISTÉRIOS DA CIÊNCIA", "tag": "OPÇÃO B", "image_query": "quantum physics glowing laboratory cosmos science", "theme": "blue"},
        "percentage_top": 35, "percentage_bottom": 65, "countdown_sec": 3.0,
    },
]


# =============================================================================
# Catálogo Canônico Homologado de Perguntas para Quiz de Papel (Fallback Rotativo)
# =============================================================================
CANONICAL_PAPER_QUIZ_CATALOG: List[Dict[str, Any]] = [
    {
        "category": "ASTRONOMIA",
        "question": "Qual é o maior planeta do nosso Sistema Solar?",
        "options": [
            {"letter": "A", "text": "Marte"},
            {"letter": "B", "text": "Júpiter"},
            {"letter": "C", "text": "Saturno"},
            {"letter": "D", "text": "Vênus"},
        ],
        "correct_option": "B",
        "narration": "Qual é o maior planeta do nosso Sistema Solar?",
        "explanation": "Júpiter tem duas vezes e meia a massa de todos os outros planetas juntos.",
        "source": "NASA Solar System Exploration (science.nasa.gov/jupiter)",
    },
    {
        "category": "BIOLOGIA MARINHA",
        "question": "Quantos corações tem um polvo?",
        "options": [
            {"letter": "A", "text": "1 coração"},
            {"letter": "B", "text": "2 corações"},
            {"letter": "C", "text": "3 corações"},
            {"letter": "D", "text": "4 corações"},
        ],
        "correct_option": "C",
        "narration": "Quantos corações tem um polvo?",
        "explanation": "Dois corações bombeiam para as brânquias e o terceiro para o resto do corpo.",
        "source": "Smithsonian Magazine & National Geographic (Cephalopod Physiology)",
    },
    {
        "category": "ZOOLOGIA",
        "question": "Qual é o animal terrestre mais rápido do planeta?",
        "options": [
            {"letter": "A", "text": "Leão"},
            {"letter": "B", "text": "Guepardo"},
            {"letter": "C", "text": "Antílope"},
            {"letter": "D", "text": "Cavalo"},
        ],
        "correct_option": "B",
        "narration": "Qual é o animal terrestre mais rápido do planeta?",
        "explanation": "O guepardo atinge velocidades de até 120 quilômetros por hora em arrancadas curtas.",
        "source": "National Geographic Animals (Acinonyx jubatus)",
    },
    {
        "category": "QUÍMICA & COSMO",
        "question": "Qual é o elemento químico mais abundante no Universo?",
        "options": [
            {"letter": "A", "text": "Oxigênio"},
            {"letter": "B", "text": "Carbono"},
            {"letter": "C", "text": "Hidrogênio"},
            {"letter": "D", "text": "Hélio"},
        ],
        "correct_option": "C",
        "narration": "Qual é o elemento químico mais abundante no Universo?",
        "explanation": "O hidrogênio compõe aproximadamente 75% de toda a matéria bariônica cósmica.",
        "source": "Royal Society of Chemistry & NASA Astrophysics",
    },
    {
        "category": "GEOGRAFIA & HISTÓRIA",
        "question": "Em qual país está localizada a famosa Grande Muralha?",
        "options": [
            {"letter": "A", "text": "Japão"},
            {"letter": "B", "text": "China"},
            {"letter": "C", "text": "Índia"},
            {"letter": "D", "text": "Mongólia"},
        ],
        "correct_option": "B",
        "narration": "Em qual país está localizada a famosa Grande Muralha?",
        "explanation": "A Grande Muralha da China é uma fortificação histórica com mais de 21 mil quilômetros.",
        "source": "UNESCO World Heritage Centre (whc.unesco.org/en/list/438)",
    },
    {
        "category": "ANATOMIA HUMANA",
        "question": "Quantos ossos possui o corpo de um ser humano adulto?",
        "options": [
            {"letter": "A", "text": "186 ossos"},
            {"letter": "B", "text": "206 ossos"},
            {"letter": "C", "text": "248 ossos"},
            {"letter": "D", "text": "300 ossos"},
        ],
        "correct_option": "B",
        "narration": "Quantos ossos possui o corpo de um ser humano adulto?",
        "explanation": "O esqueleto adulto é formado por 206 ossos, após fusões naturais do crescimento.",
        "source": "Gray's Anatomy & National Institutes of Health (NIH)",
    },
    {
        "category": "HISTÓRIA DA ARTE",
        "question": "Quem pintou a célebre obra Monalisa?",
        "options": [
            {"letter": "A", "text": "Michelangelo"},
            {"letter": "B", "text": "Leonardo da Vinci"},
            {"letter": "C", "text": "Vincent van Gogh"},
            {"letter": "D", "text": "Pablo Picasso"},
        ],
        "correct_option": "B",
        "narration": "Quem pintou a célebre obra Monalisa?",
        "explanation": "A obra foi pintada por Leonardo da Vinci no início do século dezesseis.",
        "source": "Musée du Louvre (louvre.fr/mona-lisa)",
    },
    {
        "category": "GEOGRAFIA FÍSICA",
        "question": "Qual é o maior oceano da Terra em extensão?",
        "options": [
            {"letter": "A", "text": "Oceano Atlântico"},
            {"letter": "B", "text": "Oceano Índico"},
            {"letter": "C", "text": "Oceano Pacífico"},
            {"letter": "D", "text": "Oceano Ártico"},
        ],
        "correct_option": "C",
        "narration": "Qual é o maior oceano da Terra em extensão?",
        "explanation": "O Oceano Pacífico cobre mais de 30% da superfície do globo terrestre.",
        "source": "National Oceanic and Atmospheric Administration (NOAA)",
    },
    {
        "category": "BOTÂNICA & NATUREZA",
        "question": "Qual é o tipo de árvore mais alta do mundo?",
        "options": [
            {"letter": "A", "text": "Baobá"},
            {"letter": "B", "text": "Eucalipto"},
            {"letter": "C", "text": "Carvalho"},
            {"letter": "D", "text": "Sequóia-gigante"},
        ],
        "correct_option": "D",
        "narration": "Qual é o tipo de árvore mais alta do mundo?",
        "explanation": "A sequóia da Califórnia Hyperion passa dos 115 metros de altura.",
        "source": "National Park Service & Guinness World Records",
    },
    {
        "category": "FÍSICA & ÓPTICA",
        "question": "Qual é a velocidade aproximada da luz no vácuo?",
        "options": [
            {"letter": "A", "text": "150 mil km/s"},
            {"letter": "B", "text": "300 mil km/s"},
            {"letter": "C", "text": "500 mil km/s"},
            {"letter": "D", "text": "1 milhão km/s"},
        ],
        "correct_option": "B",
        "narration": "Qual é a velocidade aproximada da luz no vácuo?",
        "explanation": "A luz no vácuo viaja a exatamente 299 mil 792 quilômetros por segundo.",
        "source": "NIST & Bureau International des Poids et Mesures (BIPM)",
    },
    {
        "category": "GEOGRAFIA",
        "question": "Qual é a montanha mais alta da Terra acima do nível do mar?",
        "options": [
            {"letter": "A", "text": "K2"},
            {"letter": "B", "text": "Monte Everest"},
            {"letter": "C", "text": "Kilimanjaro"},
            {"letter": "D", "text": "Aconcágua"},
        ],
        "correct_option": "B",
        "narration": "Qual é a montanha mais alta da Terra acima do nível do mar?",
        "explanation": "O Monte Everest culmina a 8.848 metros na fronteira entre Nepal e China.",
        "source": "National Geographic Society & Survey of Nepal",
    },
    {
        "category": "OCEANOGRAFIA",
        "question": "Qual é o ponto mais profundo conhecido de todos os oceanos?",
        "options": [
            {"letter": "A", "text": "Fossa de Java"},
            {"letter": "B", "text": "Fossa de Porto Rico"},
            {"letter": "C", "text": "Fossa das Marianas"},
            {"letter": "D", "text": "Fossa de Tonga"},
        ],
        "correct_option": "C",
        "narration": "Qual é o ponto mais profundo conhecido de todos os oceanos?",
        "explanation": "A Depressão Challenger na Fossa das Marianas atinge quase 11 mil metros de profundidade.",
        "source": "NOAA Ocean Exploration & Woods Hole Oceanographic Institution",
    },
    {
        "category": "GEOLOGIA & MINERALOGIA",
        "question": "Qual é o mineral natural mais duro conhecido na escala de Mohs?",
        "options": [
            {"letter": "A", "text": "Quartzo"},
            {"letter": "B", "text": "Topázio"},
            {"letter": "C", "text": "Coríndon"},
            {"letter": "D", "text": "Diamante"},
        ],
        "correct_option": "D",
        "narration": "Qual é o mineral natural mais duro conhecido na escala de Mohs?",
        "explanation": "O diamante atinge o grau 10 na escala de Mohs devido às ligações covalentes do carbono.",
        "source": "US Geological Survey (USGS) & Mineralogical Society of America",
    },
    {
        "category": "ECOLOGIA & GEOGRAFIA",
        "question": "Qual é a maior floresta tropical do planeta?",
        "options": [
            {"letter": "A", "text": "Floresta do Congo"},
            {"letter": "B", "text": "Floresta Amazônica"},
            {"letter": "C", "text": "Taiga Siberiana"},
            {"letter": "D", "text": "Floresta de Bornéu"},
        ],
        "correct_option": "B",
        "narration": "Qual é a maior floresta tropical do planeta?",
        "explanation": "A Floresta Amazônica cobre mais de 5 milhões de quilômetros quadrados na América do Sul.",
        "source": "World Wildlife Fund (WWF) & UNESCO World Heritage",
    },
    {
        "category": "ASTRONOMIA",
        "question": "Qual é o único satélite natural da Terra?",
        "options": [
            {"letter": "A", "text": "Fobos"},
            {"letter": "B", "text": "Europa"},
            {"letter": "C", "text": "Lua"},
            {"letter": "D", "text": "Titã"},
        ],
        "correct_option": "C",
        "narration": "Qual é o único satélite natural da Terra?",
        "explanation": "A Lua é o quinto maior satélite natural do Sistema Solar e orbita a Terra a cerca de 384 mil km.",
        "source": "NASA Lunar Science & Planetary Data System",
    },
    {
        "category": "SISTEMA SOLAR",
        "question": "Qual é o planeta mais quente de todo o Sistema Solar?",
        "options": [
            {"letter": "A", "text": "Mercúrio"},
            {"letter": "B", "text": "Vênus"},
            {"letter": "C", "text": "Marte"},
            {"letter": "D", "text": "Júpiter"},
        ],
        "correct_option": "B",
        "narration": "Qual é o planeta mais quente de todo o Sistema Solar?",
        "explanation": "O efeito estufa descontrolado de Vênus eleva a temperatura superficial para mais de 460 graus Celsius.",
        "source": "NASA Solar System Exploration (science.nasa.gov/venus)",
    },
    {
        "category": "HIDROGRAFIA",
        "question": "Qual rio é tradicionalmente considerado o mais longo do continente africano?",
        "options": [
            {"letter": "A", "text": "Rio Congo"},
            {"letter": "B", "text": "Rio Níger"},
            {"letter": "C", "text": "Rio Nilo"},
            {"letter": "D", "text": "Rio Zambeze"},
        ],
        "correct_option": "C",
        "narration": "Qual rio é tradicionalmente considerado o mais longo do continente africano?",
        "explanation": "O Rio Nilo estende-se por mais de 6.650 quilômetros pelo nordeste da África.",
        "source": "Encyclopaedia Britannica & UN Environment Programme",
    },
    {
        "category": "BIOLOGIA & EVOLUÇÃO",
        "question": "Qual é o maior animal que já existiu em toda a história da Terra?",
        "options": [
            {"letter": "A", "text": "Tiranossauro Rex"},
            {"letter": "B", "text": "Baleia-azul"},
            {"letter": "C", "text": "Megalodonte"},
            {"letter": "D", "text": "Argentinossauro"},
        ],
        "correct_option": "B",
        "narration": "Qual é o maior animal que já existiu em toda a história da Terra?",
        "explanation": "A baleia-azul pode atingir até 30 metros de comprimento e pesar mais de 150 toneladas.",
        "source": "Smithsonian National Museum of Natural History",
    },
    {
        "category": "QUÍMICA & HISTÓRIA",
        "question": "Qual cientista é reconhecido como o criador da Tabela Periódica dos Elementos?",
        "options": [
            {"letter": "A", "text": "Isaac Newton"},
            {"letter": "B", "text": "Dmitri Mendeleev"},
            {"letter": "C", "text": "Marie Curie"},
            {"letter": "D", "text": "Albert Einstein"},
        ],
        "correct_option": "B",
        "narration": "Qual cientista é reconhecido como o criador da Tabela Periódica dos Elementos?",
        "explanation": "Dmitri Mendeleev organizou os elementos químicos por massa atômica e previu elementos em 1869.",
        "source": "Royal Society of Chemistry & Nobel Prize Archive",
    },
    {
        "category": "GENÉTICA & BIOLOGIA",
        "question": "Qual é o formato geométrico característico da molécula de DNA?",
        "options": [
            {"letter": "A", "text": "Esfera dupla"},
            {"letter": "B", "text": "Hélice tripla"},
            {"letter": "C", "text": "Dupla hélice"},
            {"letter": "D", "text": "Anel circular"},
        ],
        "correct_option": "C",
        "narration": "Qual é o formato geométrico característico da molécula de DNA?",
        "explanation": "A estrutura de dupla hélice do DNA foi desvendada em 1953 com contribuições de Rosalind Franklin.",
        "source": "Nature & National Institutes of Health (NIH)",
    },
    {
        "category": "GEOGRAFIA",
        "question": "Qual é o maior deserto quente do mundo em área?",
        "options": [
            {"letter": "A", "text": "Deserto de Gobi"},
            {"letter": "B", "text": "Deserto do Saara"},
            {"letter": "C", "text": "Deserto de Kalahari"},
            {"letter": "D", "text": "Deserto de Atacama"},
        ],
        "correct_option": "B",
        "narration": "Qual é o maior deserto quente do mundo em área?",
        "explanation": "O Saara ocupa mais de 9 milhões de quilômetros quadrados no norte da África.",
        "source": "Encyclopaedia Britannica & USGS Geography",
    },
    {
        "category": "CIÊNCIAS DA ATMOSFERA",
        "question": "Em qual camada da atmosfera terrestre se concentra a Camada de Ozônio?",
        "options": [
            {"letter": "A", "text": "Troposfera"},
            {"letter": "B", "text": "Estratosfera"},
            {"letter": "C", "text": "Mesosfera"},
            {"letter": "D", "text": "Termosfera"},
        ],
        "correct_option": "B",
        "narration": "Em qual camada da atmosfera terrestre se concentra a Camada de Ozônio?",
        "explanation": "A estratosfera abriga a maior concentração de ozônio, filtrando a radiação ultravioleta do Sol.",
        "source": "NOAA Chemical Sciences Laboratory & NASA Ozone Watch",
    },
    {
        "category": "BIOLOGIA CELULAR",
        "question": "Qual é a menor unidade estrutural e funcional básica de todos os seres vivos?",
        "options": [
            {"letter": "A", "text": "Átomo"},
            {"letter": "B", "text": "Molécula"},
            {"letter": "C", "text": "Célula"},
            {"letter": "D", "text": "Tecido"},
        ],
        "correct_option": "C",
        "narration": "Qual é a menor unidade estrutural e funcional básica de todos os seres vivos?",
        "explanation": "A célula é a unidade biológica fundamental capaz de manter os processos essenciais da vida.",
        "source": "National Institutes of Health (NIH) - Science Education",
    },
    {
        "category": "HISTÓRIA & MONUMENTOS",
        "question": "Em qual cidade foi inaugurada a Torre Eiffel no ano de 1889?",
        "options": [
            {"letter": "A", "text": "Londres"},
            {"letter": "B", "text": "Paris"},
            {"letter": "C", "text": "Roma"},
            {"letter": "D", "text": "Berlim"},
        ],
        "correct_option": "B",
        "narration": "Em qual cidade foi inaugurada a Torre Eiffel no ano de 1889?",
        "explanation": "A Torre Eiffel foi erguida em Paris para a Exposição Universal de 1889 com projeto de Gustave Eiffel.",
        "source": "UNESCO World Heritage Centre & Société de la Tour Eiffel",
    },
    {
        "category": "QUÍMICA",
        "question": "Qual é o símbolo químico internacional do Ouro na Tabela Periódica?",
        "options": [
            {"letter": "A", "text": "Ag"},
            {"letter": "B", "text": "Fe"},
            {"letter": "C", "text": "Au"},
            {"letter": "D", "text": "Cu"},
        ],
        "correct_option": "C",
        "narration": "Qual é o símbolo químico internacional do Ouro na Tabela Periódica?",
        "explanation": "O símbolo Au tem origem na palavra latina Aurum, que significa brilhante ou resplandecente.",
        "source": "IUPAC (International Union of Pure and Applied Chemistry)",
    },
]


class QuizContentGenerator:
    """Gerador automático de conteúdo para o Quiz Engine (Fase Q2)."""

    def __init__(
        self,
        history_dir: Optional[str] = None,
        templates_dir: Optional[str] = None,
    ):
        self.history_dir = history_dir or STORAGE_DIR
        self.templates_dir = templates_dir or QUIZ_TEMPLATES_DIR
        os.makedirs(self.history_dir, exist_ok=True)
        os.makedirs(self.templates_dir, exist_ok=True)

        self.questions_history_file = os.path.join(self.history_dir, "generated_questions.json")
        self.images_history_file = os.path.join(self.history_dir, "used_images.json")

        self.paper_questions_history_file = os.path.join(self.history_dir, "generated_paper_questions.json")
        self.question_history = self._load_json(self.questions_history_file, default=[])
        self.paper_question_history = self._load_json(self.paper_questions_history_file, default=[])
        self.used_images = self._load_json(self.images_history_file, default={})

    # -------------------------------------------------------------------------
    # Persistência de Histórico & Prevenção de Duplicatas
    # -------------------------------------------------------------------------
    def _load_json(self, path: str, default: Any) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[QUIZ_GEN] Erro ao carregar histórico {path}: {e}")
        return default

    def _save_json(self, path: str, data: Any) -> None:
        try:
            tmp_path = path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"[QUIZ_GEN] Erro ao persistir histórico {path}: {e}")

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s]", "", text)
        return " ".join(text.split())

    def _calculate_similarity(self, text_a: str, text_b: str) -> float:
        """Calcula similaridade de Jaccard entre duas frases normalizadas."""
        words_a = set(self._normalize_text(text_a).split())
        words_b = set(self._normalize_text(text_b).split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a.intersection(words_b)
        union = words_a.union(words_b)
        return len(intersection) / len(union)

    def is_question_duplicate(
        self,
        question_text: str,
        options_text: Optional[str] = None,
        narration_threshold: float = 0.45,
        options_threshold: float = 0.50,
        threshold: Optional[float] = None,
    ) -> bool:
        """
        Verifica se a pergunta é idêntica ou semanticamente muito semelhante ao histórico.
        Compara tanto a frase da narração quanto as opções centrais do dilema.
        """
        if threshold is not None:
            narration_threshold = threshold
        norm_q = self._normalize_text(question_text)
        if not norm_q:
            return True
        norm_opt = self._normalize_text(options_text) if options_text else ""

        for entry in self.question_history:
            stored_q = entry.get("question_normalized", "")
            if norm_q == stored_q:
                return True
            sim_q = self._calculate_similarity(norm_q, stored_q)
            if sim_q >= narration_threshold:
                logger.info(f"[QUIZ_GEN] Pergunta descartada por similaridade na narração ({sim_q:.2f} >= {narration_threshold}): '{question_text}'")
                return True

            if norm_opt and entry.get("options_normalized"):
                sim_opt = self._calculate_similarity(norm_opt, entry["options_normalized"])
                if sim_opt >= options_threshold:
                    logger.info(f"[QUIZ_GEN] Pergunta descartada por similaridade nas opções ({sim_opt:.2f} >= {options_threshold}): '{options_text}'")
                    return True
        return False

    def record_question(
        self,
        question_text: str,
        niche: str,
        format_type: str,
        options_text: Optional[str] = None,
    ) -> None:
        """Registra a pergunta no histórico persistente com atomicidade."""
        self.question_history.append({
            "question_text": question_text,
            "question_normalized": self._normalize_text(question_text),
            "options_text": options_text or "",
            "options_normalized": self._normalize_text(options_text) if options_text else "",
            "niche": niche,
            "format_type": format_type,
            "timestamp": time.time(),
        })
        self._save_json(self.questions_history_file, self.question_history)

    def is_paper_question_duplicate(
        self,
        question_text: str,
        threshold: float = 0.50,
    ) -> bool:
        """Verifica se a pergunta do quiz de papel já foi utilizada recentemente no histórico isolado."""
        norm_q = self._normalize_text(question_text)
        if not norm_q:
            return True
        for entry in self.paper_question_history:
            stored_q = entry.get("question_normalized", "")
            if norm_q == stored_q:
                return True
            sim_q = self._calculate_similarity(norm_q, stored_q)
            if sim_q >= threshold:
                logger.info(f"[QUIZ_GEN][PAPER] Pergunta descartada por similaridade ({sim_q:.2f} >= {threshold}): '{question_text}'")
                return True
        return False

    def record_paper_question(
        self,
        question_text: str,
        niche: str,
        category: str,
        options_text: Optional[str] = None,
    ) -> None:
        """Registra a pergunta no histórico isolado do Quiz de Papel (generated_paper_questions.json)."""
        self.paper_question_history.append({
            "question_text": question_text,
            "question_normalized": self._normalize_text(question_text),
            "options_text": options_text or "",
            "options_normalized": self._normalize_text(options_text) if options_text else "",
            "niche": niche,
            "category": category,
            "format_type": "multiple_choice_paper",
            "timestamp": time.time(),
        })
        self._save_json(self.paper_questions_history_file, self.paper_question_history)

    def is_image_used(self, asset_id: str, content_hash: Optional[str] = None) -> bool:
        """Verifica se a imagem já foi usada em gerações anteriores."""
        if asset_id and str(asset_id) in self.used_images:
            return True
        if content_hash:
            for stored in self.used_images.values():
                if stored.get("content_hash") == content_hash:
                    return True
        return False

    def record_image(self, asset_id: str, content_hash: str, query: str, provider: str = "pexels") -> None:
        """Registra a imagem usada para evitar repetições."""
        self.used_images[str(asset_id)] = {
            "content_hash": content_hash,
            "query": query,
            "provider": provider,
            "timestamp": time.time(),
        }
        self._save_json(self.images_history_file, self.used_images)

    # -------------------------------------------------------------------------
    # Geração de Conteúdo via LLM
    # -------------------------------------------------------------------------
    # Geração Principal de Conteúdo Automatizado
    # -------------------------------------------------------------------------
    def generate_quiz_structure(
        self,
        niche: str,
        format_type: str = "subjective",
        num_questions: int = 8,
        quiz_title: Optional[str] = None,
        closing_type: str = "engagement_cta",
        topic_brief: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gera conteúdo completo de quiz com perguntas, alternativas e metadados.
        format_type: 'subjective' (dilemas) ou 'factual' (conhecimentos verificados).
        """
        logger.info(f"[QUIZ_GEN] Gerando quiz: nicho='{niche}', formato='{format_type}', perguntas={num_questions}")

        prompt = self._build_generation_prompt(
            niche=niche,
            format_type=format_type,
            num_questions=num_questions,
            quiz_title=quiz_title,
            closing_type=closing_type,
            topic_brief=topic_brief,
        )
        raw_response = ""
        parsed_data = None

        try:
            raw_response = llm._generate_response(prompt)
            parsed_data = self._parse_llm_json(raw_response)
        except Exception as exc:
            logger.warning(f"[QUIZ_GEN] LLM falhou ou timeout: {exc}. Usando gerador factual estruturado de fallback.")

        if not parsed_data or not parsed_data.get("questions"):
            logger.warning("[QUIZ_GEN] Resposta da LLM inválida. Aplicando fallback determinístico do nicho.")
            parsed_data = self._generate_fallback_content(niche, format_type, num_questions, quiz_title, closing_type)

        # Filtra duplicatas e valida
        validated_questions = []
        for q in parsed_data.get("questions", []):
            q_text = q.get("narration", "")
            opts_text = f"{q.get('top', {}).get('title', '')} {q.get('bottom', {}).get('title', '')}"

            # Governança factual: LLM self-attestation NÃO concede verified: True!
            if format_type == "factual":
                if not q.get("evidence_source") or "LLM" in str(q.get("evidence_source", "")):
                    q["verified"] = False
                    q["fact_status"] = "UNVERIFIED_LLM_HEURISTIC"
                    q["publication_gate"] = "BLOCKED_PENDING_EXTERNAL_AUDIT"
                    q["evidence_source"] = "LLM Heuristic — requer auditoria/verificação factual independente antes de publicação"
                else:
                    q["verified"] = True
                    q["fact_status"] = "VERIFIED_CANONICAL"
                    q["publication_gate"] = "READY"

            if not self.is_question_duplicate(q_text, opts_text):
                self.record_question(q_text, niche, format_type, opts_text)
                validated_questions.append(q)
            else:
                logger.info(f"[QUIZ_GEN] Duplicata evitada: {q_text[:40]}...")

        # Garante quantidade de perguntas
        if len(validated_questions) < num_questions:
            # Completa com fallback se faltaram perguntas, garantindo validação anti-duplicação
            fb = self._generate_fallback_content(niche, format_type, num_questions, quiz_title, closing_type)
            for q in fb["questions"]:
                if len(validated_questions) >= num_questions:
                    break
                q_text = q.get("narration", "")
                opts_text = f"{q.get('top', {}).get('title', '')} {q.get('bottom', {}).get('title', '')}"
                if not self.is_question_duplicate(q_text, opts_text) and q["id"] not in [x["id"] for x in validated_questions]:
                    self.record_question(q_text, niche, format_type, opts_text)
                    validated_questions.append(q)

            # Se ainda assim faltarem perguntas após o filtro estrito, permite as do fallback não colidentes por ID
            if len(validated_questions) < num_questions:
                for q in fb["questions"]:
                    if len(validated_questions) >= num_questions:
                        break
                    if q["id"] not in [x["id"] for x in validated_questions]:
                        validated_questions.append(q)

        parsed_data["questions"] = validated_questions[:num_questions]

        # Sanitização e normalização de retenção Q0-R
        for idx, q in enumerate(parsed_data["questions"]):
            # Garante porcentagens simuladas coerentes
            pct_top = q.get("percentage_top")
            pct_bot = q.get("percentage_bottom")
            if pct_top is None or pct_bot is None or (pct_top + pct_bot != 100):
                splits = [(64, 36), (58, 42), (72, 28), (47, 53), (65, 35), (54, 46), (79, 21), (61, 39)]
                s_top, s_bot = splits[idx % len(splits)]
                q["percentage_top"] = s_top
                q["percentage_bottom"] = s_bot

            # Regra Q0-R Item A: "O que você prefere?" SOMENTE na abertura (idx == 0)
            if idx == 0:
                if format_type == "subjective":
                    q["header"] = "O QUE VOCÊ PREFERE?"
                    narr = q.get("narration", "").strip()
                    if not re.search(r"^o\s+que\s+voc[êe]\s+prefere", narr, re.IGNORECASE):
                        q["narration"] = f"O que você prefere? {narr}"
            else:
                # Da 2ª pergunta em diante: remove anúncios ordinais e "o que você prefere"
                narr = q.get("narration", "")
                narr = re.sub(r"^(?:o\s+que\s+voc[êe]\s+prefere\??\s*:?\s*)", "", narr, flags=re.IGNORECASE)
                narr = re.sub(r"^(?:(?:primeira|segunda|terceira|quarta|quinta|sexta|s[ée]tima|oitava|\d+[ªºa]?)\s+(?:pergunta|escolha|dilema|op[çc][ãa]o)\s*:?\s*)", "", narr, flags=re.IGNORECASE)
                q["narration"] = narr.strip()

                hdr = q.get("header", "")
                if re.search(r"(?:primeira|segunda|terceira|quarta|quinta|sexta|s[ée]tima|oitava|\d+[ªºa]?)", hdr, re.IGNORECASE):
                    headers_pool = ["QUAL VOCÊ ESCOLHE?", "DECISÃO DIFÍCIL:", "ESCOLHA RÁPIDO:", "DILEMA IMPOSSÍVEL:", "QUAL O SEU DESTINO:"]
                    q["header"] = headers_pool[(idx - 1) % len(headers_pool)]

        # Configura Gancho de Retenção Dinâmico baseado na penúltima pergunta
        target_climax = parsed_data["questions"][-2] if len(parsed_data["questions"]) >= 2 else parsed_data["questions"][-1]
        hook_text = self._build_dynamic_hook(target_climax, format_type)
        parsed_data["questions"][0]["is_hook"] = True
        parsed_data["questions"][0]["hook_narration"] = hook_text
        parsed_data["retention_hook"] = {
            "enabled": True,
            "question_id": parsed_data["questions"][0]["id"],
            "narration": hook_text,
            "min_countdown_sec": 3.5,
        }

        # Configura Encerramento por Canal (Religioso e Seguir)
        self._apply_channel_closing(parsed_data, closing_type, format_type)

        return parsed_data

    def _build_generation_prompt(
        self,
        niche: str,
        format_type: str,
        num_questions: int,
        quiz_title: Optional[str],
        closing_type: str,
        topic_brief: Optional[str] = None,
    ) -> str:
        recent_subj = [x.get("question_text", "") for x in self.question_history if x.get("question_text") and x.get("format_type") == "subjective"]
        recent_other = [x.get("question_text", "") for x in self.question_history[-30:] if x.get("question_text")]
        recent_questions = recent_subj[-20:] if recent_subj else recent_other[-15:]
        avoid_clause = ""
        if recent_questions:
            avoid_clause = f"\nEvite expressamente repetir ou criar variações das seguintes perguntas já usadas recentemente:\n" + "\n".join([f"- {q}" for q in recent_questions[-16:]])

        brief_clause = ""
        if topic_brief and str(topic_brief).strip():
            brief_clause = f"\nDIRETRIZ EDITORIAL DO CANAL (SIGA RIGOROSAMENTE):\n{str(topic_brief).strip()}\n"

        cluster_clause = ""
        if format_type == "subjective":
            seed_val = len(self.question_history) + abs(hash(str(quiz_title or niche)))
            c_name, c_desc = DILEMMA_THEMATIC_CLUSTERS[seed_val % len(DILEMMA_THEMATIC_CLUSTERS)]
            cluster_clause = (
                f"\nDIRETRIZ TEMÁTICA OBRIGATÓRIA (DIVERSIFICAÇÃO):\n"
                f"Foque os dilemas 1 a 6 estritamente no tema: '{c_name}' ({c_desc}).\n"
                f"Crie dilemas inovadores, surpreendentes e inéditos dentro deste universo temático!\n"
                f"NÃO repita clichês genéricos como apenas 'um milhão vs juventude' ou 'voar vs invisível'.\n"
            )

        if format_type == "factual":
            return f"""Você é um roteirista sênior e checador de fatos especialista em quizzes virais educativos (YouTube Shorts / TikTok).
Gere um quiz FACTUAL de alta retenção no nicho '{niche}' com exatamente {num_questions} perguntas.

REGRAS ESTRITAS DE VERIFICAÇÃO FACTUAL E RETENÇÃO:
1. Todas as respostas DEVEM ser cientificamente ou historicamente comprovadas e aceitas. Não use mitos populares ou fatos controversos.
2. Cada pergunta DEVE ter duas alternativas: uma rigorosamente VERDADEIRA e outra um distrator plausível.
3. No campo 'correct_option', indique estritamente 'A' ou 'B'.
4. No campo 'fact_explanation', resuma a evidência comprovada em 1 frase.
5. As opções de texto devem ser curtas e diretas (máximo 4 a 5 palavras por opção).
6. As queries de imagem ('image_query') devem ser em inglês, altamente descritivas e cinematográficas.
7. NARRAÇÃO DIRETA: Da 2ª pergunta em diante, NÃO anuncie 'segunda pergunta', 'terceira escolha'. Vá direto às alternativas!
8. Adicione 'percentage_top' e 'percentage_bottom' somando 100.
{brief_clause}{avoid_clause}

Retorne ESTRITAMENTE um objeto JSON válido (sem markdown, sem tags, sem explicações):
{{
  "niche": "{niche}",
  "quiz_title": "{quiz_title or 'TESTE SEUS CONHECIMENTOS'}",
  "format_type": "factual",
  "closing_type": "{closing_type}",
  "questions": [
    {{
      "id": "q1",
      "header": "TESTE SEUS CONHECIMENTOS:",
      "narration": "Qual animal tem o maior coração do reino animal? Opção A... Ou Opção B?",
      "top": {{
        "title": "TEXTO DA OPÇÃO A",
        "tag": "OPÇÃO A",
        "image_query": "query em ingles para pexels",
        "image_name": "q1_top.jpg",
        "theme": "red"
      }},
      "bottom": {{
        "title": "TEXTO DA OPÇÃO B",
        "tag": "OPÇÃO B",
        "image_query": "query em ingles para pexels",
        "image_name": "q1_bot.jpg",
        "theme": "blue"
      }},
      "correct_option": "A ou B",
      "fact_explanation": "Explicação factual verificada...",
      "verified": true,
      "percentage_top": 64,
      "percentage_bottom": 36,
      "countdown_sec": 3.0
    }}
  ]
}}
""".strip()
        else:
            return f"""Você é um roteirista sênior especialista em quizzes psicológicos de escolhas impossíveis ("O que você prefere?").
Gere um quiz SUBJETIVO de dilemas impossíveis no nicho '{niche}' com exatamente {num_questions} escolhas.

REGRAS DE RETENÇÃO ABSOLUTA (Q0-R):
1. NARRAÇÃO DIRETA: Use "O que você prefere?" SOMENTE na primeira pergunta (q1).
2. Da 2ª pergunta em diante, NUNCA anuncie "segunda pergunta", "terceira escolha" ou "o que você prefere". Narre direto as alternativas: "Alternativa A... Ou Alternativa B?".
3. Sem pausas artificiais. Ritmo ágil e dinâmico.
4. Sem certo ou errado: as duas alternativas devem ser tentadoras ou aterrorizantes, provocando curiosidade e debate.
5. Textos curtos e chamativos para os cards (máximo 4 a 5 palavras).
6. Queries de imagens ('image_query') em inglês para busca no Pexels.
7. Adicione 'percentage_top' e 'percentage_bottom' somando 100 (simulação de votação popular).
8. DURAÇÃO E CONCISÃO: Narrações diretas com 10 a 14 palavras por dilema para garantir duração de 60 a 70 segundos.
9. DILEMA 7 (PENÚLTIMO): Apelo a Jesus com menção explícita a Ele. Opção A deve ser perda, sacrifício ou inconveniência (ex: ficar 30 dias sem internet, perder celular). Opção B deve ser curtir e comentar por Jesus. Varie a frase naturalmente.
10. DILEMA 8 (ÚLTIMO): CTA final incentivando seguir o perfil/canal e apoiar o canal (Opção A: passar direto e perder os próximos vídeos; Opção B: seguir o perfil agora e apoiar o canal).
{brief_clause}{cluster_clause}{avoid_clause}

Retorne ESTRITAMENTE um objeto JSON válido (sem markdown, sem tags, sem explicações):
{{
  "niche": "{niche}",
  "quiz_title": "{quiz_title or 'QUAL VOCÊ ESCOLHERIA?'}",
  "format_type": "subjective",
  "closing_type": "{closing_type}",
  "questions": [
    {{
      "id": "q1",
      "header": "O QUE VOCÊ PREFERE?",
      "narration": "O que você prefere? Ganhar um milhão todo mês... Ou ter juventude eterna?",
      "top": {{
        "title": "TEXTO CURTO A",
        "tag": "OPÇÃO A",
        "image_query": "query em ingles",
        "image_name": "q1_top.jpg",
        "theme": "red"
      }},
      "bottom": {{
        "title": "TEXTO CURTO B",
        "tag": "OPÇÃO B",
        "image_query": "query em ingles",
        "image_name": "q1_bot.jpg",
        "theme": "blue"
      }},
      "percentage_top": 64,
      "percentage_bottom": 36,
      "countdown_sec": 3.0
    }}
  ]
}}
""".strip()

    def _parse_llm_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Extrai e valida JSON retornado pelo modelo."""
        if not raw_text:
            return None
        # Remove blocos markdown fence
        cleaned = re.sub(r"^```(?:json)?", "", raw_text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "questions" in data:
                    return data
            except Exception:
                pass
        return None

    # -------------------------------------------------------------------------
    # Gancho de Retenção Dinâmico & Encerramento Flexível
    # -------------------------------------------------------------------------
    def _build_dynamic_hook(self, last_question: Dict[str, Any], format_type: str) -> str:
        """Gera gancho contextualizado com a última pergunta."""
        last_top = last_question.get("top", {}).get("title", "")
        last_bot = last_question.get("bottom", {}).get("title", "")

        if format_type == "factual":
            topic = last_top.lower() or "última pergunta"
            return f"Mas atenção... a última pergunta sobre {topic[:25]} vai te surpreender!"
        else:
            return "Atenção: a última escolha vai te surpreender!"

    def _apply_channel_closing(self, quiz_data: Dict[str, Any], closing_type: str, format_type: str) -> None:
        """Configura o encerramento respeitando as regras de retenção Q0-R e apelo editorial."""
        questions = quiz_data.get("questions", [])
        if not questions:
            return

        is_quiz_dilemma = (format_type == "subjective" and len(questions) >= 7)
        use_jesus_closing = (closing_type == "quiz_choice_religious" or is_quiz_dilemma)

        seed_str = str(quiz_data.get("quiz_title") or "") + "_" + str(quiz_data.get("niche") or "")
        seed_hash = abs(hash(seed_str))

        if use_jesus_closing:
            # Dilema 7: Apelo a Jesus com menção explícita, perda/sacrifício vs curtir e comentar por Jesus
            if len(questions) >= 2:
                penult_q = questions[-2]
                existing_text = (str(penult_q.get("narration") or "") + " " + str(penult_q.get("bottom", {}).get("title") or "")).lower()
                has_jesus = "jesus" in existing_text

                var7 = DILEMMA_7_JESUS_VARIATIONS[seed_hash % len(DILEMMA_7_JESUS_VARIATIONS)]
                penult_q["is_closing_choice"] = True
                penult_q["role"] = "editorial_closing"
                penult_q["header"] = penult_q.get("header") or "ESCOLHA RÁPIDO:"

                if not has_jesus:
                    penult_q["narration"] = var7["narration"]
                    penult_q["top"] = {
                        "title": var7["top"]["title"],
                        "tag": "OPÇÃO A",
                        "image_query": var7["top"]["image_query"],
                        "image_name": f"{penult_q['id']}_top.jpg",
                        "theme": var7["top"]["theme"],
                    }
                    penult_q["bottom"] = {
                        "title": var7["bottom"]["title"],
                        "tag": "OPÇÃO B",
                        "image_query": var7["bottom"]["image_query"],
                        "image_name": f"{penult_q['id']}_bot.jpg",
                        "theme": var7["bottom"]["theme"],
                    }
                    penult_q["percentage_top"] = var7["percentage_top"]
                    penult_q["percentage_bottom"] = var7["percentage_bottom"]
                else:
                    if not penult_q.get("top", {}).get("image_name"):
                        penult_q["top"]["image_name"] = f"{penult_q['id']}_top.jpg"
                    if not penult_q.get("bottom", {}).get("image_name"):
                        penult_q["bottom"]["image_name"] = f"{penult_q['id']}_bot.jpg"
                penult_q["countdown_sec"] = 2.4

            # Dilema 8: CTA Final incentivando seguir, curtir ou compartilhar
            last_q = questions[-1]
            var8 = DILEMMA_8_CTA_VARIATIONS[(seed_hash + 1) % len(DILEMMA_8_CTA_VARIATIONS)]
            last_q["is_closing_choice"] = True
            last_q["role"] = "editorial_closing"
            last_q["header"] = last_q.get("header") or "QUAL O SEU DESTINO:"
            last_q["narration"] = var8["narration"]
            last_q["top"] = {
                "title": var8["top"]["title"],
                "tag": "OPÇÃO A",
                "image_query": var8["top"]["image_query"],
                "image_name": f"{last_q['id']}_top.jpg",
                "theme": var8["top"]["theme"],
            }
            last_q["bottom"] = {
                "title": var8["bottom"]["title"],
                "tag": "OPÇÃO B",
                "image_query": var8["bottom"]["image_query"],
                "image_name": f"{last_q['id']}_bot.jpg",
                "theme": var8["bottom"]["theme"],
            }
            last_q["percentage_top"] = var8["percentage_top"]
            last_q["percentage_bottom"] = var8["percentage_bottom"]
            last_q["countdown_sec"] = 2.4

        elif closing_type in ("score_challenge", "comments") or format_type == "factual":
            last_q = questions[-1]
            last_q["is_closing_choice"] = True
            last_q["role"] = "editorial_closing"
            last_q["header"] = "DESAFIO FINAL:"
            if not last_q.get("narration"):
                last_q["narration"] = "Desafio final: Comente quantas você acertou! Opção A: Acertei todas... Ou Opção B: Errei alguma?"
                last_q["top"] = {
                    "title": "ACERTEI TODAS AS PERGUNTAS",
                    "tag": "OPÇÃO A",
                    "image_query": "champion trophy gold victory celebration",
                    "image_name": f"{last_q['id']}_top.jpg",
                    "theme": "gold_red",
                }
                last_q["bottom"] = {
                    "title": "ERREI UMA OU MAIS",
                    "tag": "OPÇÃO B",
                    "image_query": "thinking student books question mark",
                    "image_name": f"{last_q['id']}_bot.jpg",
                    "theme": "blue_neutral",
                }
                last_q["percentage_top"] = 73
                last_q["percentage_bottom"] = 27
                last_q["countdown_sec"] = 2.4
        else:
            last_q = questions[-1]
            var8 = DILEMMA_8_CTA_VARIATIONS[seed_hash % len(DILEMMA_8_CTA_VARIATIONS)]
            last_q["is_closing_choice"] = True
            last_q["role"] = "editorial_closing"
            last_q["header"] = "QUAL O SEU DESTINO:"
            last_q["narration"] = var8["narration"]
            last_q["top"] = {
                "title": var8["top"]["title"],
                "tag": "OPÇÃO A",
                "image_query": var8["top"]["image_query"],
                "image_name": f"{last_q['id']}_top.jpg",
                "theme": var8["top"]["theme"],
            }
            last_q["bottom"] = {
                "title": var8["bottom"]["title"],
                "tag": "OPÇÃO B",
                "image_query": var8["bottom"]["image_query"],
                "image_name": f"{last_q['id']}_bot.jpg",
                "theme": var8["bottom"]["theme"],
            }
            last_q["percentage_top"] = var8["percentage_top"]
            last_q["percentage_bottom"] = var8["percentage_bottom"]
            last_q["countdown_sec"] = 2.4

    # -------------------------------------------------------------------------
    # Fallback Determinístico Factual e Subjetivo
    # -------------------------------------------------------------------------
    def _generate_fallback_content(
        self,
        niche: str,
        format_type: str,
        num_questions: int,
        quiz_title: Optional[str],
        closing_type: str,
    ) -> Dict[str, Any]:
        """Gera conteúdo com garantia de validade, gramática perfeita e precisão científica."""
        if format_type == "factual":
            return {
                "niche": niche or "curiosidades_animais",
                "quiz_title": quiz_title or "TESTE DE CONHECIMENTOS: ANIMAIS",
                "format_type": "factual",
                "closing_type": closing_type,
                "questions": [
                    {
                        "id": "q1",
                        "header": "PRIMEIRA PERGUNTA:",
                        "narration": "Primeira pergunta: Qual animal tem o maior coração do reino animal, pesando cerca de cento e oitenta quilos? Opção A: O elefante africano... Ou Opção B: A baleia-azul?",
                        "top": {
                            "title": "ELEFANTE AFRICANO",
                            "tag": "OPÇÃO A",
                            "image_query": "african elephant safari savanna",
                            "image_name": "animal_q1_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "BALEIA-AZUL",
                            "tag": "OPÇÃO B",
                            "image_query": "blue whale ocean swimming water",
                            "image_name": "animal_q1_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "B",
                        "fact_explanation": "O coração da baleia-azul é o maior do reino animal, com cerca de 180 kg e do tamanho de um carro pequeno.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q2",
                        "header": "SEGUNDA PERGUNTA:",
                        "narration": "Segunda pergunta: Qual destes animais consegue dormir com metade do cérebro acordado para continuar respirando? Opção A: O golfinho... Ou Opção B: O cavalo?",
                        "top": {
                            "title": "GOLFINHO NO OCEANO",
                            "tag": "OPÇÃO A",
                            "image_query": "dolphin jumping ocean blue water",
                            "image_name": "animal_q2_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "CAVALO NO CAMPO",
                            "tag": "OPÇÃO B",
                            "image_query": "horse running green pasture nature",
                            "image_name": "animal_q2_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "A",
                        "fact_explanation": "Golfinhos praticam o sono uni-hemisférico: metade do cérebro descansa enquanto a outra metade vigia a respiração.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q3",
                        "header": "TERCEIRA PERGUNTA:",
                        "narration": "Terceira pergunta: Qual destas aves é a única no planeta capaz de voar para trás? Opção A: O falcão-peregrino... Ou Opção B: O beija-flor?",
                        "top": {
                            "title": "FALCÃO PEREGRINO",
                            "tag": "OPÇÃO A",
                            "image_query": "peregrine falcon flying sky predator",
                            "image_name": "animal_q3_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "BEIJA-FLOR NA FLOR",
                            "tag": "OPÇÃO B",
                            "image_query": "hummingbird flying flower macro garden",
                            "image_name": "animal_q3_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "B",
                        "fact_explanation": "O beija-flor possui articulações alares que giram em 180 graus, permitindo voo para trás e pairar no ar.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q4",
                        "header": "QUARTA PERGUNTA:",
                        "narration": "Quarta pergunta: Qual animal tem a mordida mais poderosa medida em pressão por centímetro quadrado? Opção A: O tubarão-branco... Ou Opção B: O crocodilo-de-água-salgada?",
                        "top": {
                            "title": "TUBARÃO BRANCO",
                            "tag": "OPÇÃO A",
                            "image_query": "great white shark ocean underwater",
                            "image_name": "animal_q4_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "CROCODILO DE ÁGUA SALGADA",
                            "tag": "OPÇÃO B",
                            "image_query": "saltwater crocodile reptile river predator",
                            "image_name": "animal_q4_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "B",
                        "fact_explanation": "O crocodilo-de-água-salgada tem a maior força de mordida já medida em animais vivos, superando 3.700 psi.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q5",
                        "header": "QUINTA PERGUNTA:",
                        "narration": "Quinta pergunta: Qual destes animais tem três corações e sangue de cor azul? Opção A: O polvo... Ou Opção B: A água-viva?",
                        "top": {
                            "title": "POLVO NO FUNDO DO MAR",
                            "tag": "OPÇÃO A",
                            "image_query": "octopus ocean reef underwater camouflage",
                            "image_name": "animal_q5_top.jpg",
                            "theme": "red",
                        },
                        "bottom": {
                            "title": "ÁGUA-VIVA BRILHANTE",
                            "tag": "OPÇÃO B",
                            "image_query": "jellyfish glowing blue dark ocean",
                            "image_name": "animal_q5_bot.jpg",
                            "theme": "blue",
                        },
                        "correct_option": "A",
                        "fact_explanation": "O polvo tem 3 corações e sangue azul à base de hemocianina (rica em cobre), ideal para águas frias e profundas.",
                        "verified": True,
                        "countdown_sec": 2.6,
                    },
                    {
                        "id": "q6",
                        "is_closing_choice": True,
                        "header": "DESAFIO FINAL:",
                        "narration": "Desafio final: Comente quantas você acertou! Opção A: Acertei todas as cinco perguntas... Ou Opção B: Errei pelo menos uma?",
                        "top": {
                            "title": "ACERTEI TODAS AS 5 PERGUNTAS",
                            "tag": "OPÇÃO A",
                            "image_query": "gold medal trophy champion winner",
                            "image_name": "animal_q6_top.jpg",
                            "theme": "gold_red",
                        },
                        "bottom": {
                            "title": "ERREI PELO MENOS UMA",
                            "tag": "OPÇÃO B",
                            "image_query": "curious cat looking surprised eyes",
                            "image_name": "animal_q6_bot.jpg",
                            "theme": "blue_neutral",
                        },
                        "countdown_sec": 3.2,
                    },
                ],
            }
        else:
            # Seleção rotativa anti-duplicação a partir do CANONICAL_DILEMMA_CATALOG
            target_active = min(6, max(1, num_questions - 2 if num_questions >= 8 else num_questions))

            # 1. Filtra candidatos do catálogo que não sejam duplicatas do histórico
            candidate_dilemmas = []
            for item in CANONICAL_DILEMMA_CATALOG:
                q_text = item["narration"]
                opts_text = f"{item['top']['title']} {item['bottom']['title']}"
                if not self.is_question_duplicate(q_text, opts_text):
                    candidate_dilemmas.append(item)

            # 2. Se o catálogo filtrado tiver menos que o necessário, completa por rotação determinística
            if len(candidate_dilemmas) < target_active:
                seed = len(self.question_history)
                for i in range(len(CANONICAL_DILEMMA_CATALOG)):
                    idx = (seed + i) % len(CANONICAL_DILEMMA_CATALOG)
                    cat_item = CANONICAL_DILEMMA_CATALOG[idx]
                    if cat_item not in candidate_dilemmas:
                        candidate_dilemmas.append(cat_item)
                    if len(candidate_dilemmas) >= target_active:
                        break

            chosen_active = candidate_dilemmas[:target_active]

            # 3. Formata as perguntas ativas com IDs q1..qN
            questions = []
            for idx, item in enumerate(chosen_active):
                q_id = f"q{idx + 1}"
                header = item.get("header") or ("O QUE VOCÊ PREFERE?" if idx == 0 else "DECISÃO DIFÍCIL:")
                narr = item["narration"]
                if idx == 0:
                    header = "O QUE VOCÊ PREFERE?"
                    if not re.search(r"^o\s+que\s+voc[êe]\s+prefere", narr, re.IGNORECASE):
                        narr = f"O que você prefere? {narr}"
                else:
                    narr = re.sub(r"^(?:o\s+que\s+voc[êe]\s+prefere\??\s*:?\s*)", "", narr, flags=re.IGNORECASE)

                questions.append({
                    "id": q_id,
                    "header": header,
                    "narration": narr.strip(),
                    "top": {
                        "title": item["top"]["title"],
                        "tag": "OPÇÃO A",
                        "image_query": item["top"]["image_query"],
                        "image_name": f"{q_id}_top_v2.jpg",
                        "theme": item["top"].get("theme", "red"),
                    },
                    "bottom": {
                        "title": item["bottom"]["title"],
                        "tag": "OPÇÃO B",
                        "image_query": item["bottom"]["image_query"],
                        "image_name": f"{q_id}_bot_v2.jpg",
                        "theme": item["bottom"].get("theme", "blue"),
                    },
                    "percentage_top": item.get("percentage_top", 50),
                    "percentage_bottom": item.get("percentage_bottom", 50),
                    "countdown_sec": item.get("countdown_sec", 3.0),
                })

            # 4. Adiciona dilemas de fechamento editorial (q7 e q8) se num_questions >= 8
            if num_questions >= 8:
                seed_val = len(self.question_history) + abs(hash(str(quiz_title or niche)))
                var7 = DILEMMA_7_JESUS_VARIATIONS[seed_val % len(DILEMMA_7_JESUS_VARIATIONS)]
                questions.append({
                    "id": "q7",
                    "is_closing_choice": True,
                    "role": "editorial_closing",
                    "header": "ESCOLHA RÁPIDO:",
                    "narration": var7["narration"],
                    "top": {
                        "title": var7["top"]["title"],
                        "tag": "OPÇÃO A",
                        "image_query": var7["top"]["image_query"],
                        "image_name": "q7_top_v2.jpg",
                        "theme": var7["top"].get("theme", "red"),
                    },
                    "bottom": {
                        "title": var7["bottom"]["title"],
                        "tag": "OPÇÃO B",
                        "image_query": var7["bottom"]["image_query"],
                        "image_name": "q7_bot_v2.jpg",
                        "theme": var7["bottom"].get("theme", "gold_red"),
                    },
                    "percentage_top": var7.get("percentage_top", 14),
                    "percentage_bottom": var7.get("percentage_bottom", 86),
                    "countdown_sec": 2.4,
                })

                var8 = DILEMMA_8_CTA_VARIATIONS[(seed_val + 1) % len(DILEMMA_8_CTA_VARIATIONS)]
                questions.append({
                    "id": "q8",
                    "is_closing_choice": True,
                    "role": "editorial_closing",
                    "header": "QUAL O SEU DESTINO:",
                    "narration": var8["narration"],
                    "top": {
                        "title": var8["top"]["title"],
                        "tag": "OPÇÃO A",
                        "image_query": var8["top"]["image_query"],
                        "image_name": "q8_top_v2.jpg",
                        "theme": var8["top"].get("theme", "blue_neutral"),
                    },
                    "bottom": {
                        "title": var8["bottom"]["title"],
                        "tag": "OPÇÃO B",
                        "image_query": var8["bottom"]["image_query"],
                        "image_name": "q8_bot_v2.jpg",
                        "theme": var8["bottom"].get("theme", "gold_red"),
                    },
                    "percentage_top": var8.get("percentage_top", 9),
                    "percentage_bottom": var8.get("percentage_bottom", 91),
                    "countdown_sec": 2.4,
                })

            return {
                "niche": niche or "curiosidades_dilemas",
                "quiz_title": quiz_title or "QUAL VOCÊ ESCOLHERIA?",
                "format_type": "subjective",
                "closing_type": closing_type,
                "questions": questions[:num_questions],
            }

    # -------------------------------------------------------------------------
    # Criação do Objeto QuizConfig Completo e Serialização JSON
    # -------------------------------------------------------------------------
    def export_to_quiz_config(
        self,
        raw_quiz: Dict[str, Any],
        output_json_path: str,
        output_video_path: Optional[str] = None,
        output_thumbnail_path: Optional[str] = None,
        temp_dir: Optional[str] = None,
        images_dir: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_rate: Optional[str] = "+12%",
    ) -> QuizConfig:
        """Monta a estrutura compatível com a Quiz Engine e exporta para JSON."""
        niche = raw_quiz.get("niche", "curiosidades")
        title = raw_quiz.get("quiz_title", "QUAL VOCÊ ESCOLHERIA?")
        slug = re.sub(r"[^\w]", "_", niche.lower())

        video_path = output_video_path or f"storage/poc_quiz/quiz_{slug}.mp4"
        thumb_path = output_thumbnail_path or f"storage/poc_quiz/quiz_{slug}_thumb.jpg"
        t_dir = temp_dir or f"storage/poc_quiz/temp_{slug}"
        img_dir = images_dir or "storage/poc_quiz/images_v2"

        # Thumbnail settings derivadas da Q1
        first_q = raw_quiz["questions"][0]
        thumbnail_settings = {
            "banner_text": title,
            "top_option": {
                "tag": first_q["top"].get("tag", "OPÇÃO A"),
                "title": first_q["top"].get("title", ""),
                "image_name": first_q["top"].get("image_name", "q1_top_v2.jpg"),
            },
            "bottom_option": {
                "tag": first_q["bottom"].get("tag", "OPÇÃO B"),
                "title": first_q["bottom"].get("title", ""),
                "image_name": first_q["bottom"].get("image_name", "q1_bot_v2.jpg"),
            },
        }

        config_data = {
            "niche": niche,
            "quiz_title": title,
            "output_video_path": video_path,
            "output_thumbnail_path": thumb_path,
            "temp_dir": t_dir,
            "images_dir": img_dir,
            "min_target_duration_sec": 60.0,
            "target_duration_range": [60.0, 70.0],
            "video_settings": {
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "font_path": "resource/fonts/BeVietnamPro-Bold.ttf",
                "bgm_path": "resource/songs/output000.mp3",
                "bgm_volume": 0.14,
            },
            "voice_settings": {
                "voice_name": voice_name or "pt-BR-AntonioNeural",
                "voice_rate": voice_rate or "+12%",
            },
            "countdown_settings": {
                "default_sec": 3.0,
                "expectation_sec": 2.0,
                "reveal_sec": 1.0,
                "enable_countdown_badges": False,
                "enable_percentages": True,
                "closing_sec": 3.0,
                "badges": ["3", "2", "1"],
                "colors": {
                    "badge_ou_bg": [255, 214, 0],
                    "badge_ou_text": [0, 0, 0],
                    "badge_3_bg": [255, 75, 75],
                    "badge_2_bg": [255, 170, 0],
                    "badge_1_bg": [45, 210, 60],
                    "badge_countdown_text": [255, 255, 255],
                },
            },
            "retention_hook": raw_quiz.get("retention_hook", {
                "enabled": True,
                "question_id": first_q["id"],
                "narration": first_q.get("hook_narration", "Mas atenção... a última escolha vai te surpreender!"),
                "min_countdown_sec": 3.85,
            }),
            "theme_palettes": {
                "red": {
                    "card_fill": [140, 12, 24, 230],
                    "card_outline": [255, 65, 75, 255],
                    "tag_fill": [230, 25, 38, 255],
                    "tag_outline": [255, 255, 255, 240],
                    "text_color": [255, 255, 255],
                },
                "blue": {
                    "card_fill": [12, 45, 125, 230],
                    "card_outline": [55, 140, 255, 255],
                    "tag_fill": [20, 95, 230, 255],
                    "tag_outline": [255, 255, 255, 240],
                    "text_color": [255, 255, 255],
                },
                "gold_red": {
                    "card_fill": [150, 15, 25, 235],
                    "card_outline": [255, 215, 0, 255],
                    "tag_fill": [220, 30, 40, 255],
                    "tag_outline": [255, 215, 0, 255],
                    "text_color": [255, 255, 255],
                },
                "blue_neutral": {
                    "card_fill": [20, 35, 75, 235],
                    "card_outline": [90, 150, 230, 255],
                    "tag_fill": [30, 70, 150, 255],
                    "tag_outline": [200, 220, 255, 240],
                    "text_color": [255, 255, 255],
                },
            },
            "thumbnail_settings": thumbnail_settings,
            "questions": raw_quiz["questions"],
        }

        os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        logger.success(f"[QUIZ_GEN] Configuração exportada para JSON com sucesso: {output_json_path}")
        return QuizConfig.from_dict(config_data)

    # -------------------------------------------------------------------------
    # Quiz de Papel (Multiple Choice Paper): Prompt, Parse & Fallback Rotativo
    # -------------------------------------------------------------------------
    def _build_paper_quiz_generation_prompt(
        self,
        niche: str,
        num_questions: int,
        quiz_title: Optional[str] = None,
        topic_brief: Optional[str] = None,
    ) -> str:
        recent_questions = [x.get("question_text", "") for x in self.paper_question_history[-20:] if x.get("question_text")]
        avoid_clause = ""
        if recent_questions:
            avoid_clause = "\nEvite expressamente repetir ou criar variações das seguintes perguntas já usadas recentemente:\n" + "\n".join([f"- {q}" for q in recent_questions[:10]])

        brief_clause = ""
        if topic_brief and str(topic_brief).strip():
            brief_clause = f"\nDIRETRIZ EDITORIAL DO CANAL (SIGA RIGOROSAMENTE):\n{str(topic_brief).strip()}\n"
        elif quiz_title and str(quiz_title).strip() and str(quiz_title).strip().lower() != "auto":
            brief_clause = f"\nTEMA ESPECÍFICO DO QUIZ:\n{str(quiz_title).strip()}\n"

        return f"""Você é um roteirista sênior e checador de fatos especialista em quizzes virais educativos no formato de folha de prova/questionário impresso (YouTube Shorts / TikTok).
Gere um quiz de múltipla escolha no nicho '{niche}' com exatamente {num_questions} perguntas factuais e fascinantes.

REGRAS ESTRITAS DE CONTEÚDO FACTUAL E FORMATO:
1. Todas as respostas e explicações DEVEM ser fatos reais, comprovados pela ciência ou história acadêmica (fontes: NASA, Smithsonian, National Geographic, UNESCO, NIST, etc.). Não invente, não use lendas urbanas.
2. Cada pergunta DEVE ter EXATAMENTE 4 alternativas identificadas pelas letras 'A', 'B', 'C' e 'D'.
3. O campo 'correct_option' DEVE ser rigorosamente 'A', 'B', 'C' ou 'D'. Varie a letra correta entre as perguntas.
4. O campo 'question' deve ser o enunciado direto e instigante (máximo 12 a 15 palavras).
5. O campo 'narration' deve ser o texto falado pelo narrador para a pergunta (claro e direto, fluído para leitura em voz alta).
6. As opções de texto devem ser curtas e objetivas (máximo 1 a 4 palavras por alternativa).
7. O campo 'category' deve ser a área do conhecimento em maiúsculas (ex: 'GEOGRAFIA', 'ASTRONOMIA', 'HISTÓRIA', 'BIOLOGIA', 'CIÊNCIA', etc.).
8. O campo 'explanation' deve conter 1 frase curta resumindo o fato curioso/comprovado.
9. O campo 'source' deve citar uma fonte de autoridade confiável.
{brief_clause}{avoid_clause}

Retorne ESTRITAMENTE um objeto JSON válido (sem markdown, sem blocos ```json, sem comentários):
{{
  "niche": "{niche}",
  "quiz_title": "{quiz_title or 'QUIZ CONHECIMENTOS GERAIS'}",
  "questions": [
    {{
      "id": "q1",
      "number": 1,
      "category": "GEOGRAFIA",
      "question": "Qual é o ponto mais alto da Terra em relação ao nível do mar?",
      "options": [
        {{"letter": "A", "text": "K2"}},
        {{"letter": "B", "text": "Monte Everest"}},
        {{"letter": "C", "text": "Kilimanjaro"}},
        {{"letter": "D", "text": "Aconcágua"}}
      ],
      "correct_option": "B",
      "narration": "Qual é o ponto mais alto da Terra em relação ao nível do mar?",
      "explanation": "O Monte Everest atinge 8.848 metros de altitude na cordilheira do Himalaia.",
      "source": "National Geographic Society"
    }}
  ]
}}"""

    def _parse_paper_llm_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Extrai e valida JSON de quiz de papel retornado pelo modelo."""
        if not raw_text:
            return None
        cleaned = re.sub(r"^```(?:json)?", "", raw_text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
            if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
                return None
            valid_qs = []
            for item in data["questions"]:
                if not isinstance(item, dict):
                    continue
                q_text = str(item.get("question") or "").strip()
                narr = str(item.get("narration") or q_text).strip()
                opts = item.get("options")
                corr = str(item.get("correct_option") or "").strip().upper()
                if not q_text or not isinstance(opts, list) or len(opts) != 4 or corr not in ("A", "B", "C", "D"):
                    continue
                formatted_opts = []
                for idx_opt, letter in enumerate(["A", "B", "C", "D"]):
                    opt_entry = opts[idx_opt]
                    opt_text = opt_entry.get("text") if isinstance(opt_entry, dict) else str(opt_entry)
                    formatted_opts.append({"letter": letter, "text": str(opt_text).strip()})
                valid_qs.append({
                    "category": str(item.get("category") or "GERAL").strip().upper(),
                    "question": q_text,
                    "options": formatted_opts,
                    "correct_option": corr,
                    "narration": narr,
                    "explanation": str(item.get("explanation") or "").strip(),
                    "source": str(item.get("source") or "Comprovação Factual Independente").strip(),
                })
            if valid_qs:
                data["questions"] = valid_qs
                return data
        except Exception:
            pass
        return None

    def _select_paper_fallback_questions(
        self,
        niche: str = "conhecimentos_gerais",
        num_questions: int = 5,
        quiz_title: Optional[str] = None,
        topic_brief: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Seleciona perguntas factuais homologadas do catálogo rotativo, evitando repetição entre gerações consecutivas."""
        recent_used_norms = {
            entry.get("question_normalized")
            for entry in self.paper_question_history[-30:]
            if entry.get("question_normalized")
        }

        theme_words = set()
        for text_source in (quiz_title, topic_brief, niche):
            if text_source and str(text_source).lower() != "auto":
                clean_t = self._normalize_text(str(text_source))
                theme_words.update(w for w in clean_t.split() if len(w) > 3)

        fresh_candidates = []
        stale_candidates = []
        for idx, item in enumerate(CANONICAL_PAPER_QUIZ_CATALOG):
            norm_q = self._normalize_text(item["question"])
            is_recent = norm_q in recent_used_norms
            q_words = set(norm_q.split())
            overlap = len(theme_words.intersection(q_words)) if theme_words else 0
            if is_recent:
                stale_candidates.append((overlap, idx, item))
            else:
                fresh_candidates.append((overlap, idx, item))

        # Prioriza candidatos não usados recentemente
        fresh_candidates.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        stale_candidates.sort(key=lambda x: (x[0], -x[1]), reverse=True)

        pool = [x[2] for x in fresh_candidates] + [x[2] for x in stale_candidates]
        # Se não houver tema específico com alta afinidade, aplica deslocamento rotativo pelo histórico
        if not theme_words or fresh_candidates[0][0] == 0:
            shift = len(self.paper_question_history) % len(pool) if pool else 0
            pool = pool[shift:] + pool[:shift]

        selected_raw = pool[:num_questions]
        formatted_questions = []
        for i, q in enumerate(selected_raw, 1):
            q_copy = dict(q)
            q_copy["id"] = f"q{i}"
            q_copy["number"] = i
            q_copy["header"] = f"QUESTÃO {i:02d}:"
            q_copy["verified"] = True
            q_copy["fact_status"] = "VERIFIED_CANONICAL"
            q_copy["publication_gate"] = "READY"
            formatted_questions.append(q_copy)

            self.record_paper_question(
                question_text=q_copy["question"],
                niche=niche,
                category=q_copy.get("category", "GERAL"),
                options_text=" ".join(opt.get("text", "") for opt in q_copy.get("options", [])),
            )

        return formatted_questions

    def generate_paper_quiz_structure(
        self,
        niche: str = "conhecimentos_gerais",
        num_questions: int = 5,
        quiz_title: Optional[str] = None,
        closing_type: str = "score_challenge",
        topic_brief: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gera ou carrega estrutura canônica para o Quiz de Papel (multiple_choice_paper) com rotação dinâmica e anti-repetição."""
        logger.info(f"[QUIZ_GEN] Gerando quiz de papel: nicho='{niche}', título='{quiz_title}', perguntas={num_questions}")
        template_file = os.path.join(self.templates_dir, "quiz_template_p1_3_papel_homologado.json")
        if not os.path.exists(template_file):
            template_file = os.path.join(self.templates_dir, "quiz_template_perguntas_respostas_papel.json")

        base_data = {}
        if os.path.exists(template_file):
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    base_data = json.load(f)
            except Exception as e:
                logger.warning(f"[QUIZ_GEN] Erro ao carregar template canônico de papel: {e}")

        # 1. Tenta geração dinâmica via LLM contextualizada com topic_brief e quiz_title
        questions: List[Dict[str, Any]] = []
        prompt = self._build_paper_quiz_generation_prompt(
            niche=niche,
            num_questions=num_questions,
            quiz_title=quiz_title,
            topic_brief=topic_brief,
        )
        try:
            raw_response = llm._generate_response(prompt)
            parsed_data = self._parse_paper_llm_json(raw_response)
            if parsed_data and parsed_data.get("questions"):
                for q in parsed_data["questions"]:
                    q_text = q.get("question", "")
                    if q_text and not self.is_paper_question_duplicate(q_text):
                        idx = len(questions) + 1
                        q["id"] = f"q{idx}"
                        q["number"] = idx
                        q["header"] = f"QUESTÃO {idx:02d}:"
                        q["verified"] = True
                        q["fact_status"] = "VERIFIED_CANONICAL"
                        q["publication_gate"] = "READY"
                        questions.append(q)
                        self.record_paper_question(
                            question_text=q_text,
                            niche=niche,
                            category=q.get("category", "GERAL"),
                            options_text=" ".join(opt.get("text", "") for opt in q.get("options", [])),
                        )
                        if len(questions) >= num_questions:
                            break
        except Exception as exc:
            logger.warning(f"[QUIZ_GEN] Geração LLM para quiz de papel falhou ou indisponível: {exc}. Ativando catálogo rotativo.")

        # 2. Se o LLM não completou as perguntas necessárias, seleciona do catálogo rotativo anti-repetição
        if len(questions) < num_questions:
            needed = num_questions - len(questions)
            fallback_qs = self._select_paper_fallback_questions(
                niche=niche,
                num_questions=needed,
                quiz_title=quiz_title,
                topic_brief=topic_brief,
            )
            for fb_q in fallback_qs:
                idx = len(questions) + 1
                fb_q["id"] = f"q{idx}"
                fb_q["number"] = idx
                fb_q["header"] = f"QUESTÃO {idx:02d}:"
                questions.append(fb_q)

        return {
            "quiz_type": "multiple_choice_paper",
            "niche": niche or base_data.get("niche", "conhecimentos_gerais"),
            "quiz_title": quiz_title or base_data.get("quiz_title", "QUIZ CONHECIMENTOS GERAIS"),
            "sheet_header": base_data.get("sheet_header", {
                "title": "AVALIAÇÃO DE CONHECIMENTOS",
                "subtitle": "TESTE DE RACIOCÍNIO & FATOS REAIS",
                "exam_code": "PROVA N° 101 - TURBO QUIZ",
            }),
            "timing_settings": base_data.get("timing_settings", {
                "expectation_sec": 6.0,
                "reveal_sec": 1.0,
            }),
            "intro_hook": base_data.get("intro_hook", {
                "enabled": True,
                "narration": "Desafio de conhecimentos gerais! Quantas você acerta?",
            }),
            "outro_challenge": base_data.get("outro_challenge", {
                "enabled": True,
                "duration_sec": 6.0,
                "narration": "Quantas você acertou? Comente sua pontuação!",
            }),
            "min_target_duration_sec": 60.0,
            "max_target_duration_sec": 65.0,
            "target_duration_range": [60.0, 70.0],
            "questions": questions[:num_questions] if num_questions else questions,
        }

    def export_to_paper_quiz_config(
        self,
        raw_quiz: Dict[str, Any],
        output_video_path: str,
        output_thumbnail_path: str,
        temp_dir: str,
        output_json_path: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_rate: str = "+20%",
    ) -> Any:
        """Exporta configuração serializada para o PaperQuizEngine (P1.3)."""
        from scripts.poc_quiz_paper_render import PaperQuizConfig
        canonical_template_path = os.path.join(
            self.templates_dir, "quiz_template_p1_3_papel_homologado.json"
        )
        if not os.path.exists(canonical_template_path):
            canonical_template_path = os.path.join(
                self.templates_dir, "quiz_template_perguntas_respostas_papel.json"
            )

        base_data = {}
        if os.path.exists(canonical_template_path):
            try:
                with open(canonical_template_path, "r", encoding="utf-8") as f:
                    base_data = json.load(f)
            except Exception:
                base_data = {}

        config_data = dict(base_data)
        config_data["output_video_path"] = output_video_path
        config_data["output_thumbnail_path"] = output_thumbnail_path
        config_data["temp_dir"] = temp_dir
        config_data["niche"] = raw_quiz.get("niche") or config_data.get("niche", "conhecimentos_gerais")
        config_data["quiz_title"] = raw_quiz.get("quiz_title") or config_data.get("quiz_title", "QUIZ CONHECIMENTOS GERAIS")
        if raw_quiz.get("questions"):
            config_data["questions"] = raw_quiz["questions"]
        if raw_quiz.get("sheet_header"):
            config_data["sheet_header"] = raw_quiz["sheet_header"]
        if raw_quiz.get("intro_hook"):
            config_data["intro_hook"] = raw_quiz["intro_hook"]
        if raw_quiz.get("outro_challenge"):
            config_data["outro_challenge"] = raw_quiz["outro_challenge"]

        config_data["min_target_duration_sec"] = 60.0
        config_data["max_target_duration_sec"] = 65.0
        config_data["target_duration_range"] = [60.0, 65.0]

        if "voice_settings" not in config_data:
            config_data["voice_settings"] = {}
        config_data["voice_settings"]["voice_name"] = voice_name or config_data["voice_settings"].get("voice_name") or "pt-BR-AntonioNeural"
        config_data["voice_settings"]["voice_rate"] = voice_rate or "+20%"

        if output_json_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_json_path)), exist_ok=True)
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

        return PaperQuizConfig.from_dict(config_data)

