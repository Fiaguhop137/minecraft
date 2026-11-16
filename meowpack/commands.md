# For most of these, you will need my texture pack!
You can find it here: [Meowpack – GitHub](https://github.com/Fiaguhop137/resource-packs/tree/main/meowpack)
>Tested only in Minecraft 26.3.
## Over-Stacked
### Over-Stacked Ender Pearls
```mcfunction
/give @p ender_pearl[max_stack_size=64] 64
```
### Over-Stacked Totems
```mcfunction
/give @p totem_of_undying[max_stack_size=64] 64
```
### Duping Bundle
```mcfunction
/give @p red_bundle[custom_name=[{"text":"Bundle of Duplication","italic":false}],max_stack_size=16] 16
```
## Super Tools
### Super Sword
```mcfunction
/give @p netherite_axe[custom_name=[{"text":"C","italic":false,"color":"#aa5500"},{"text":"l","italic":false,"color":"#aa470e"},{"text":"a","italic":false,"color":"#aa391c"},{"text":"r","italic":false,"color":"#aa2b2b"},{"text":"e","italic":false,"color":"#aa1c39"},{"text":"n","italic":false,"color":"#aa0e47"},{"text":"t","italic":false,"color":"#aa0055"}],lore=[[{"text":"Bloodburning V","italic":false,"color":"dark_purple"}],[{"text":"Vampyric III","italic":false}]],enchantment_glint_override=false,enchantments={fire_aspect:3},attribute_modifiers=[{type:attack_damage,amount:2048,slot:mainhand,operation:add_multiplied_total,id:"clarent1"},{type:attack_damage,amount:2048,slot:mainhand,operation:add_multiplied_total,id:"clarent2"},{type:attack_damage,amount:2048,slot:mainhand,operation:add_multiplied_total,id:"clarent3"},{type:attack_speed,amount:1024,slot:mainhand,id:"clarent",operation:add_value},{type:block_break_speed,amount:-1,operation:add_multiplied_total,id:"clarent"},{type:entity_interaction_range,amount:64,id:"clarent",operation:add_value}],unbreakable={},item_model="meowpack:clarent",tooltip_display={hidden_components:[enchantments]}]
```
### Super Pickaxe
```mcfunction
/give @p netherite_pickaxe[custom_name=[{"text":"World Eater","italic":false}],lore=[[{"text":"Efficiency ∞","italic":false,"color":"gray"}]],rarity=epic,enchantments={efficiency:255,silk_touch:1},attribute_modifiers=[{type:block_break_speed,amount:1024,operation:add_multiplied_total,id:"world"},{type:block_break_speed,amount:1024,operation:add_multiplied_total,id:"eater"}],unbreakable={},item_model="meowpack:world_eater",tooltip_display={hidden_components:[enchantments]}]
```
### Super Bow
```mcfunction
/give @p crossbow[custom_name=[{"text":"Mortifer Eminus","italic":false}],enchantments={flame:1,infinity:1,piercing:255,power:255,quick_charge:255},unbreakable={},item_model="meowpack:mortifer_eminus"]
```
### Super Spear
```mcfunction
/give @p netherite_spear[custom_name=[{"text":"Hasta Inferni","italic":false}],rarity=epic,enchantments={bane_of_arthropods:255,fire_aspect:255,sharpness:255,smite:255,lunge:17},attribute_modifiers=[{type:attack_damage,amount:2048,slot:mainhand,operation:add_multiplied_total,id:"1785111002654"},{type:attack_speed,amount:1024,slot:mainhand,operation:add_multiplied_total,id:"1785111002655"}],unbreakable={}]
```
### Super Trident
```mcfunction
/give @p trident[custom_name=[{"text":"Furca Inferni","italic":false}],rarity=epic,enchantments={bane_of_arthropods:255,channeling:1,fire_aspect:255,impaling:255,loyalty:17,sharpness:255,smite:255},attribute_modifiers=[{type:attack_damage,amount:2048,operation:add_multiplied_total,id:"1785111146065"},{type:attack_speed,amount:1024,operation:add_multiplied_total,id:"1785111146066"}],unbreakable={}]
```
## Special Equipment
### Phoenix Wings
```mcfunction
/give @p elytra[custom_name=[{"text":"Phoenix Wings","italic":false}],rarity=epic,equippable={slot:chest,asset_id:"phoenixwings:phoenix_wings"},max_damage=225,repairable={items:[blaze_powder]},item_model="phoenixwings:phoenix_wings"]
```
### Bunny Boots
```mcfunction
/give @p leather_boots[dyed_color=13016423,custom_name=[{"text":"Bunny Boots","italic":false}],attribute_modifiers=[{type:step_height,amount:0.65,slot:feet,id:"bunny_boots_step",operation:add_value}],max_damage=225,repairable={items:[rabbit_foot]},item_model="bunnyboots:bunny_boots",tooltip_display={hidden_components:[dyed_color]}]
```
## Ardens Set
### Sword
```mcfunction
/give @p netherite_sword[custom_name=[{"text":"Ensis Ardens","italic":false}],rarity=epic,enchantments={bane_of_arthropods:10,fire_aspect:10,looting:10,sharpness:10,smite:10,sweeping_edge:10,breach:10},unbreakable={},item_model="meowpack:ensis_ardens"]
```
### Sickle
```mcfunction
/give @p netherite_axe[custom_name=[{"text":"Falcula Ardens","italic":false}],rarity=epic,enchantments={bane_of_arthropods:10,efficiency:10,fire_aspect:10,sharpness:10,silk_touch:1,smite:10,breach:10},unbreakable={},item_model="meowpack:falcula_ardens"]
```
### Scythe
```mcfunction
/give @p netherite_hoe[custom_name=[{"text":"Falx Ardens","italic":false}],rarity=epic,enchantments={bane_of_arthropods:10,efficiency:10,fire_aspect:10,fortune:10,looting:10,sharpness:10,smite:10,breach:10},unbreakable={},item_model="meowpack:falx_ardens"]
```
### Elytraplate
```mcfunction
/give @p netherite_chestplate[custom_name=[{"text":"Mammae Ardens","italic":false}],rarity=epic,enchantments={blast_protection:10,fire_protection:10,projectile_protection:10,protection:10,thorns:10},glider={},unbreakable={},item_model="meowpack:mammae_ardens",equippable={slot:"chest",asset_id:"meowpack:mammae_ardens"}]
```
### Heart of the Nether
```mcfunction
/give @p clock[custom_name=[{"text":"Heart of the Nether","italic":false}],rarity=epic,enchantment_glint_override=true,attribute_modifiers=[{type:armor,amount:30,operation:add_multiplied_total,id:"nether_heart"},{type:block_interaction_range,amount:64,id:"nether_heart",operation:add_value},{type:entity_interaction_range,amount:64,id:"nether_heart",operation:add_value},{type:max_health,amount:256,id:"nether_heart",operation:add_value}],death_protection={death_effects:[{type:apply_effects,effects:[{id:regeneration,duration:1e+34,amplifier:255,ShowParticles:0b,ShowIcon:0b}]}]},item_model="meowpack:nether_heart"]
```
## Potions
### Splash Potion of Invulnerability
```mcfunction
/give @p splash_potion[potion_contents={custom_color:4673362,custom_effects:[{id:resistance,duration:9600,amplifier:5,show_particles:0b}]},custom_name=[{"text":"Splash Potion of Invulnerability","italic":false}]]
```
### God Potion
```mcfunction
/give @p potion[potion_contents={custom_color:8606770,custom_effects:[{id:absorption,duration:1200,amplifier:255,show_icon:0b},{id:conduit_power,duration:1200,amplifier:255,show_icon:0b},{id:dolphins_grace,duration:1200,amplifier:255,show_icon:0b},{id:fire_resistance,duration:1200,amplifier:1,show_icon:0b},{id:glowing,duration:1200,amplifier:1},{id:haste,duration:1200,amplifier:255,show_icon:0b},{id:health_boost,duration:1200,amplifier:255,show_icon:0b},{id:hero_of_the_village,duration:1200,amplifier:255,show_icon:0b},{id:invisibility,duration:1200,amplifier:1,show_icon:0b},{id:jump_boost,duration:1200,amplifier:3,show_icon:0b},{id:luck,duration:1200,amplifier:255,show_icon:0b},{id:night_vision,duration:1200,amplifier:1,show_icon:0b},{id:regeneration,duration:1200,amplifier:255,show_icon:0b},{id:saturation,duration:1200,amplifier:255,show_icon:0b},{id:speed,duration:1200,amplifier:5,show_icon:0b},{id:strength,duration:1200,amplifier:255,show_icon:0b},{id:water_breathing,duration:1200,amplifier:1,show_icon:0b}]},custom_name=[{"text":"G","italic":false,"color":"dark_red"},{"text":"o","italic":false,"color":"red"},{"text":"d","italic":false,"color":"gold"},{"text":" ","italic":false,"color":"yellow"},{"text":"P","italic":false,"color":"dark_green"},{"text":"o","italic":false,"color":"green"},{"text":"t","italic":false,"color":"aqua"},{"text":"i","italic":false,"color":"dark_aqua"},{"text":"o","italic":false,"color":"dark_blue"},{"text":"n","italic":false,"color":"blue"}],enchantment_glint_override=true,food={can_always_eat:1b,nutrition:1,saturation:1},consumable={consume_seconds:0,animation:drink},tooltip_display={hidden_components:[potion_contents]},!use_remainder]
```
### Splash Potion of Instant Death
```mcfunction
/give @p splash_potion[potion_contents={custom_color:11141205,custom_effects:[{id:instant_damage,duration:17,amplifier:29,ambient:1b,show_particles:0b,show_icon:0b},{id:instant_health,duration:17,amplifier:29,ambient:1b,show_particles:0b,show_icon:0b}]},custom_name=[{"text":"Splash Potion of Instant Death","italic":false}]]
```
### Prank Apple
```mcfunction
/give @p potion[potion_contents={custom_effects:[{id:instant_health,duration:17,amplifier:125,show_particles:0b,show_icon:0b}]},custom_name=[{"text":"Enchanted Golden Apple","italic":false}],rarity=rare,enchantment_glint_override=true,food={nutrition:4,saturation:9.6,can_always_eat:1b},consumable={consume_seconds:0,animation:none},max_stack_size=64,!use_remainder,item_model="minecraft:golden_apple",tooltip_display={hidden_components:[potion_contents]}]
```
## Infinite Bread
Arrange the parts in this order:
**A + (B repeated x times) + (C repeated x times) + D**
This generates x+2 bread. The construction can be extended until reaching the 32,500-character command block limit(can be extended with mods).
### Infinite Bread - Part A
```mcfunction
/give @p minecraft:bread[consumable={consume_seconds:0},food={can_always_eat:1b,nutrition:5,saturation:6},use_remainder={id:"minecraft:bread",components:{consumable:{consume_seconds:0},food:{can_always_eat:1b,nutrition:5,saturation:6},
```
### Infinite Bread - Part B
```mcfunction
use_remainder:{id:"minecraft:bread",components:{consumable:{consume_seconds:0},food:{can_always_eat:1b,nutrition:5,saturation:6},
```
### Infinite Bread - Part C
```mcfunction
}}
```
### Infinite Bread - Part D
```mcfunction
}}] 64
```
## IMMORTALITY
Arrange the parts in alphabetical order:
**A + (B repeated as many times as desired) + C**
### IMMORTALITY - Part A
```mcfunction
/give @p red_bundle[bundle_contents=[
```
### IMMORTALITY - Part B
```mcfunction
{id:totem_of_undying,count:64,components:{max_stack_size:64}},
```
### IMMORTALITY - Part C
```mcfunction
],custom_name=[{"text":"IMMORTALITY","italic":false}],rarity=epic]
```
