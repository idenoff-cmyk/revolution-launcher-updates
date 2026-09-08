# Модпак Revolution: перевірка наданих файлів

Дата: 2026-09-08. Minecraft 1.21.1 / NeoForge 21.1.250.

Надано **97 JAR-файлів, 376.66 МіБ**. Вони скопійовані без зміни вмісту, версій або назв. Для кожного файла обчислено SHA-256; CRC ZIP-контейнерів перевірені. Основні mod ID не дублюються.

За метаданими JAR та вкладених Jar-in-Jar бібліотек виконано 393 перевірки залежностей, діапазонів, несумісностей та версії FML на стороні клієнта. Невідомих обов’язкових mod ID та невідповідностей серед перевірених правил не виявлено. Попередній аудит без додаткових FML-перевірок містив 292 правила.

Для порівняння використано справжній Maven VersionRange 3.8.5 із бібліотек NeoForge. Враховано штатну VersionSupportMatrix із FML 4.0.44: для Minecraft 1.21.1 допускаються також правила, що приймають 1.21 (і NeoForge 21.0.166). Саме тому вузькі діапазони двох Pufferfish-модів не означають автоматичної несумісності. Вміст модів не патчився.

Це статична перевірка, а не підтвердження запуску: вона не перевіряє виконання mixin-коду, взаємодію модів у світі, реальне обрання всіх вкладених бібліотек або відповідність серверним налаштуванням. Подальший запуск із готового EXE поза Codex підтвердив завершення інсталяції NeoForge, ініціалізацію клієнта та вихід із кодом 0. Гра у світі й на сервері ще потребує перевірки; див. QA.md.

**Конфігурації не надані.** У комплекті є лише передані JAR-файли. Якщо серверна збірка потребує config, defaultconfigs, kubejs або scripts, ці каталоги слід додати окремо. Світи, акаунти та особисті файли Minecraft не копіювалися.

**Нативна перевірка встановлення:** фінальний Revolution.exe встановив 97 файлів, виявив одну навмисно пошкоджену тестову копію та успішно відновив її з комплекту.

## Використання комплекту

Папка `modpack` має лежати поруч із Revolution.exe. У стандартному інстансі Revolution Modded файли комплекту встановлюються автоматично при першому відкритті. Далі перевіряється налаштований підписаний канал. Кнопки перевірки й відновлення звіряють SHA-256; для відповідних файлів використовуються локальний комплект або перевірений кеш, а нові файли завантажуються. Для перевірки актуальності каналу та підготовки Java, Minecraft і NeoForge потрібен інтернет.

Інші інстанси залишаються окремими. Якщо задано HTTPS manifestUrl, використовується підписаний серверний маніфест. Локальне джерело `bundle` у віддаленому маніфесті не дозволено. `docs/modpack-manifest.json` — локальний індекс комплекту; для каналу підготуйте й підпишіть реліз інструментом `tools.release_tool`, як описано в [UPDATES.md](UPDATES.md). Експорт із лаунчера створює лише чернетку.

## Авторство та ліцензії модів

MIT стосується коду лаунчера. Моди з наданої користувачем папки зберігають власні ліцензії та авторство; наведені нижче значення прочитані з їхніх метаданих. Ця локальна поставка не публікувалася на хостингу.

| Файл | Mod ID / версія | Ліцензія з метаданих |
|---|---|---|
| [Neoforge]ctov-3.6.3.jar | ctov 3.6.3 | BY-NC-ND-4.0 |
| accessories-neoforge-1.1.0-beta.53+1.21.1.jar | accessories 1.1.0-beta.53+1.21.1 | MIT |
| ApothicAttributes-1.21.1-2.10.1.jar | apothic_attributes 2.10.1 | MIT License |
| ApothicEnchanting-1.21.1-1.6.2.jar | apothic_enchanting 1.6.2 | MIT License |
| architectury-13.0.11-neoforge.jar | architectury 13.0.11 | GNU LGPLv3 |
| badpackets-neo-0.8.2.jar | badpackets 0.8.2 | Apache-2.0 |
| baguettelib-1.21.1-NeoForge-2.0.6.jar | baguettelib 2.0.6 | MIT |
| bettercombat-neoforge-2.4.0+1.21.1.jar | bettercombat 2.4.0+1.21.1 | All Rights Reserved |
| biolith-neoforge-3.0.14.jar | biolith 3.0.14 | LGPL-3.0 |
| BiomesOPlenty-neoforge-1.21.1-21.1.0.14.jar | biomesoplenty 21.1.0.14 | All Rights Reserved |
| boss_companions-1.0.1-neoforge-1.21.1.jar | boss_companions 1.0.1 | All Rights Reserved |
| brutalbosses-1.21.1-8.6.jar | brutalbosses 8.6 | ARR |
| cloth-config-15.0.140-neoforge.jar | cloth_config 15.0.140 | GNU LGPLv3 |
| Clumps-neoforge-1.21.1-19.0.0.1.jar | clumps 19.0.0.1 | MIT |
| combat_roll-neoforge-2.0.6+1.21.1.jar | combat_roll 2.0.6+1.21.1 | GPL-3.0 |
| copycats-3.0.8+mc.1.21.1-neoforge.jar | copycats 3.0.8+mc.1.21.1-neoforge | All Rights Reserved |
| cosmeticarmorreworkedforked-neoforge-1.21.1-0.0.4.jar | cosmeticarmorreworkedforked 1.21.1-0.0.4 | MIT |
| create-1.21.1-6.0.10.jar | create 6.0.10 | Read attached LICENSE.md |
| create-aeronautics-bundled-1.21.1-1.3.2.jar | aeronautics_bundled 1.3.2 | Read attached LICENSE.md |
| create_aeronautics_ftb_chunks-1.21.1-NeoForge-1.1.1.jar | create_aeronautics_ftb_chunks 1.1.1 | MIT |
| cupboard-1.21.1-4.1.jar | cupboard 4.1 | ARR |
| curios-neoforge-9.5.1+1.21.1.jar | curios 9.5.1+1.21.1 | LGPL-3.0-or-later |
| DoggyTalentsNext-1.21.1-1.19.1.jar | doggytalents 1.19.1 | GNU LGPLv3 |
| DungeonsArise-1.21.1-2.1.68-release.jar | dungeons_arise 2.1.68 | All Rights Reserved |
| ecologics-1.21.1-2.3.7.jar | ecologics 2.3.7 | MIT |
| FallingTree-1.21.1-1.21.1.11.jar | fallingtree 1.21.1.11 | LGPL-3.0 |
| FarmersDelight-1.21.1-1.3.4.jar | farmersdelight 1.3.4 | MIT License |
| fdbosses-3.2-1.21.1.jar | fdbosses 3.2 | All Rights Reserved |
| fdlib-1.0.9-1.21.1.jar | fdlib 1.0.9 | All Rights Reserved |
| ferritecore-7.0.3-neoforge.jar | ferritecore 7.0.3 | MIT |
| ftb-chunks-neoforge-2101.1.22.jar | ftbchunks 2101.1.22 | All Rights Reserved |
| ftb-library-neoforge-2101.1.35.jar | ftblibrary 2101.1.35 | All Rights Reserved |
| ftb-teams-neoforge-2101.1.11.jar | ftbteams 2101.1.11 | All Rights Reserved |
| fzzy_config-0.7.6+1.21+neoforge.jar | fzzy_config 0.7.6+1.21+neoforge | TDL-M (https://github.com/fzzyhmstrs/Timefall-Development-Licence-Modified) |
| geckolib-neoforge-1.21.1-4.9.2.jar | geckolib 4.9.2 | MIT |
| GlitchCore-neoforge-1.21.1-2.1.0.2.jar | glitchcore 2.1.0.2 | All Rights Reserved |
| gml-6.0.2.jar | gml 6.0.2 | MIT |
| gravestone-neoforge-1.21.1-1.0.40.jar | gravestone 1.21.1-1.0.40 | All rights reserved |
| gravestonecurioscompat-1.21.1-NeoForge-4.0.2.jar | gravestonecurioscompat 4.0.2 | MIT |
| hapi-neoforge-1.21.1-1.0.0.jar | hapi 1.0.0 | MIT |
| hybrid_aquatic-neoforge-1.21.1-1.7.0.jar | hybrid_aquatic 1.7.0 | ARR |
| Incendium_1.21.x_v5.4.4.jar | incendium 5.4.3 | Stardust Labs License |
| invtweaks-1.21.1-1.3.2.jar | invtweaks 1.21.1-1.3.2 | Apache License, Version 2.0 |
| irons_lib-1.21.1-2.1.0.jar | irons_lib 1.21.1-2.1.0 | All Rights Reserved |
| irons_spellbooks-1.21.1-3.16.3.jar | irons_spellbooks 1.21.1-3.16.3 | All Rights Reserved |
| jei-1.21.1-neoforge-19.51.0.417.jar | jei 19.51.0.417 | The MIT License (MIT) |
| kotlinforforge-5.12.0-all.jar | Вкладені бібліотеки / language provider | Див. ліцензії всередині JAR |
| L_Ender's Cataclysm 1.21.1-3.33.jar | cataclysm 3.33 | All assets of The Cataclysm are unlicensed and all rights are reserved to them by MCL_Ender. The source code LGPL v3.0 license |
| lionfishapi-3.1.jar | lionfishapi 3.1 | LGPL |
| lithostitched-1.8.0+beta4-neoforge-21.1.jar | lithostitched 1.8.0+beta4 | MIT |
| mermod-neoforge-3.3.2+1.21.1.jar | mermod 3.3.2 | MPL-2.0 |
| modernfix-neoforge-5.27.24+mc1.21.1.jar | modernfix 5.27.24+mc1.21.1 | GNU LGPL 3.0 |
| MoogsEndStructures-1.21-2.0.3.jar | mes 2.0.3 | GNU Lesser General Public License v3.0 |
| MoogsMissingVillages-1.21-2.1.2.jar | mmv 2.1.2 | GNU Lesser General Public License v3.0 |
| MoogsNetherStructures-1.21-3.0.0.jar | mns 3.0.0 | GNU Lesser General Public License v3.0 |
| MoogsSoaringStructures-1.21-2.1.2.jar | mss 2.1.2 | GNU Lesser General Public License v3.0 |
| MoogsStructureLib-neoforge-1.21.1-3.1.2.jar | moogs_structures 3.1.2 | https://github.com/FinnSetchell/MoogsStructureLib/blob/1.21.5/LICENSE |
| MoogsTemplesReimagined-universal-1.21-2.0.2.jar | mtr 2.0.2 | GNU Lesser General Public License v3.0 |
| MoogsVoyagerStructures-universal-1.21-5.1.1.jar | mvs 5.1.1 | GNU Lesser General Public License v3.0 |
| MutantMonsters-v21.1.1-1.21.1-NeoForge.jar | mutantmonsters 21.1.1 | AGPL-3.0-or-later |
| noisium-neoforge-2.7.0+mc1.21-1.21.1.jar | noisium 2.7.0+mc1.21-1.21.1 | LGPL-3.0 |
| owo-lib-neoforge-0.12.15.5-beta.1+1.21.jar | owo 0.12.15.5-beta.1+1.21 | MIT |
| Placebo-1.21.1-9.9.2.jar | placebo 9.9.2 | MIT License |
| player-animation-lib-forge-2.0.4+1.21.1.jar | playeranimator 2.0.4+1.21.1 | MIT |
| pufferfish_unofficial_additions-1.21.1-2.2.8.jar | pufferfish_unofficial_additions 2.2.8 | MIT License |
| puffish_attributes-0.8.3-1.21-neoforge.jar | puffish_attributes 0.8.3 | LGPL-3.0 |
| puffish_skills-0.19.0-1.21-neoforge.jar | puffish_skills 0.19.0 | All Rights Reserved |
| PuzzlesLib-v21.1.56-mc1.21.1-NeoForge.jar | puzzleslib 21.1.56 | MPL-2.0 |
| RPG ST2.jar | rpg_skill_trees2 1.0 | Unlicense |
| sable-neoforge-1.21.1-2.0.5.jar | sable 2.0.5 | PolyForm Shield License 1.0.0 |
| SereneSeasons-neoforge-1.21.1-10.1.0.3.jar | sereneseasons 10.1.0.3 | All Rights Reserved |
| simplehats-neoforge-1.21.1-0.4.0.jar | simplehats 0.4.0 | Code: MIT, Assets: ARR |
| simplyswords-neoforge-1.70.2-1.21.1.jar | simplyswords 1.70.2-1.21.1 | Timefall Development License |
| SimplyTooltips-neoforge-0.1.5.jar | simplytooltips 0.1.5 | Timefall Development License 1.2 |
| sophisticatedbackpacks-1.21.1-3.25.78.2107.jar | sophisticatedbackpacks 3.25.78 | All Rights Reserved |
| sophisticatedcore-1.21.1-1.4.90.2299.jar | sophisticatedcore 1.4.90 | All Rights Reserved |
| spell_engine-neoforge-1.10.5+1.21.1.jar | spell_engine 1.10.5 | GPL-3.0 |
| spell_power-neoforge-1.6.0+1.21.1.jar | spell_power 1.6.0+1.21.1 | GPL-3.0 |
| TerraBlender-neoforge-1.21.1-4.1.0.8.jar | terrablender 4.1.0.8 | LGPLv3 |
| toms_storage-1.21-2.4.2.jar | toms_storage 2.4.2 | MIT License https://github.com/tom5454/Toms-Storage/blob/master/LICENSE |
| twilightforest-1.21.1-4.8.3345-universal.jar | twilightforest 4.8.3345 | GNU LESSER GENERAL PUBLIC LICENSE Version 2.1 |
| upgraded-iron-chests-1.4.jar | upgraded_chests 1.4 | All Rights Reserved |
| voicechat-neoforge-1.21.1-2.6.22.jar | voicechat 1.21.1-2.6.22, voicechat_api 2.6.20 | All rights reserved |
| YungsApi-1.21.1-NeoForge-5.1.8.jar | yungsapi 1.21.1-NeoForge-5.1.8 | LGPLv3 |
| YungsBetterCaves-1.21.1-NeoForge-3.1.6.jar | bettercaves 1.21.1-NeoForge-3.1.6 | LGPLv3 |
| YungsBetterDesertTemples-1.21.1-NeoForge-4.1.5.jar | betterdeserttemples 1.21.1-NeoForge-4.1.5 | LGPLv3 |
| YungsBetterDungeons-1.21.1-NeoForge-5.1.4.jar | betterdungeons 1.21.1-NeoForge-5.1.4 | LGPLv3 |
| YungsBetterEndIsland-1.21.1-NeoForge-3.1.2.jar | betterendisland 1.21.1-NeoForge-3.1.2 | LGPLv3 |
| YungsBetterJungleTemples-1.21.1-NeoForge-3.1.2.jar | betterjungletemples 1.21.1-NeoForge-3.1.2 | LGPLv3 |
| YungsBetterMineshafts-1.21.1-NeoForge-5.1.1.jar | bettermineshafts 1.21.1-NeoForge-5.1.1 | LGPLv3 |
| YungsBetterNetherFortresses-1.21.1-NeoForge-3.1.5.jar | betterfortresses 1.21.1-NeoForge-3.1.5 | LGPLv3 |
| YungsBetterOceanMonuments-1.21.1-NeoForge-4.1.2.jar | betteroceanmonuments 1.21.1-NeoForge-4.1.2 | LGPLv3 |
| YungsBetterStrongholds-1.21.1-NeoForge-5.1.3.jar | betterstrongholds 1.21.1-NeoForge-5.1.3 | LGPLv3 |
| YungsBetterWitchHuts-1.21.1-NeoForge-4.1.1.jar | betterwitchhuts 1.21.1-NeoForge-4.1.1 | LGPLv3 |
| YungsBridges-1.21.1-NeoForge-5.1.1.jar | yungsbridges 1.21.1-NeoForge-5.1.1 | LGPLv3 |
| YungsCaveBiomes-1.21.1-NeoForge-3.1.1.jar | yungscavebiomes 1.21.1-NeoForge-3.1.1 | ARR |
| YungsExtras-1.21.1-NeoForge-5.1.1.jar | yungsextras 1.21.1-NeoForge-5.1.1 | LGPLv3 |

## Технічні джерела

- [NeoForge: mod files та dependency metadata](https://docs.neoforged.net/docs/1.21.1/gettingstarted/modfiles/).
- Локальний офіційний loader-4.0.44.jar: VersionSupportMatrix перевірена через javap; jar-файли модів прочитані як ZIP/TOML/JSON без виконання їхнього коду.
