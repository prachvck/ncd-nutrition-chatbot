# food_id -> corrected food_type ('dish' or 'ingredient')
# Built by manual review, batch by batch. Only entries that DIFFER from the
# current keyword-classifier output need to be listed here.
OVERRIDES = {}
# --- batch 1 (rows 0-150) ---
OVERRIDES.update({
    21986: 'ingredient',  # coconut milk, canned - cooking ingredient not a dish
    22318: 'dish',        # basil beef stir-fry - real dish, missed by keyword
    22376: 'dish',        # kha-nom thuai - Thai dessert dish
    21790: 'ingredient',  # euro cake (packaged snack cake)
    22167: 'ingredient',  # prune bread (plain bread)
    21785: 'ingredient',  # white bread
    21846: 'ingredient',  # vitamin bread
    22083: 'ingredient',  # honey wholewheat bread
    21874: 'ingredient',  # wholewheat bread
    22202: 'ingredient',  # fine wholewheat bread
    22243: 'ingredient',  # sweet butter bread
    22730: 'ingredient',  # raisin bread
    22496: 'ingredient',  # butter bread with icing
    22779: 'ingredient',  # sandwich bread (the loaf, not an assembled sandwich)
    22357: 'ingredient',  # wholewheat sandwich bread (loaf)
    22780: 'ingredient',  # wholewheat bread
    22676: 'ingredient',  # thick wheat bread
    22757: 'ingredient',  # raisin filled bread (sweet filling -> snack, not meal)
    22282: 'ingredient',  # pumpkin cereal bread
    22481: 'dish',        # kha-nom piak poon - classic Thai dessert dish
    22298: 'ingredient',  # bread cubic (plain bread)
})
# --- batch 2 (rows 151-300) ---
OVERRIDES.update({
    22440: 'dish',        # sticky rice garlic liver - full rice dish
    22435: 'dish',        # sticky rice larb - full rice dish
    22313: 'dish',        # sticky rice & grilled pork - full rice dish
    22429: 'dish',        # garlic chicken rice - full rice dish
    22220: 'dish',        # omelette rice - full rice dish
    22608: 'dish',        # double sandwich ham/pork floss - assembled sandwich
    22164: 'ingredient',  # cubic bread wholewheat (plain bread)
    22165: 'ingredient',  # cubic bread wholewheat riceberry (plain bread)
    22135: 'ingredient',  # cubic wholewheat riceberry bread (plain bread)
    22632: 'dish',        # cookie cake - substantial dessert (keep as dish)
    22160: 'ingredient',  # Ovaltine sandwich COOKIE - cookie snack, "sandwich" false-triggered dish
    22247: 'dish',        # salapao red pork - savory filled bun, meal-like
    22144: 'dish',        # salapao riceberry bun
    22181: 'dish',        # salapao red pork
    22569: 'dish',        # tom yum mullet fish - soup dish, "tom yum" not in keyword list
    22568: 'dish',        # tom klong crispy fish - sour soup dish
    22793: 'dish',        # tiramisu - substantial dessert
    22054: 'ingredient',  # canned tuna in water - protein ingredient, not a dish ("canned" false-triggered)
})
# --- batch 3 (rows 301-450) ---
OVERRIDES.update({
    21813: 'ingredient',  # evaporated milk - "canned" false-triggered
    22133: 'ingredient',  # canned tuna branded "sandwich tuna" - still just canned tuna
    22331: 'ingredient',  # sukiyaki dipping sauce - condiment
    21849: 'ingredient',  # sesame oil - cooking ingredient, "salad" false-triggered
    21879: 'ingredient',  # olive oil - cooking ingredient, "salad" false-triggered
    22704: 'ingredient',  # instant noodle block, no seasoning - raw ingredient not prepared dish
    22646: 'dish',        # noodles mixed with moroheiya - noodle dish
    22053: 'ingredient',  # canned tuna steak in oil - "canned" false-triggered
    22152: 'ingredient',  # dried shredded fish (fish floss) - topping, not a dish
    22155: 'ingredient',
    22156: 'ingredient',
    22153: 'ingredient',
    22154: 'ingredient',
    22151: 'ingredient',
    21845: 'ingredient',  # curry POWDER - spice/seasoning, "curry" false-triggered
    22344: 'dish',        # stir-fried tofu with clear noodle
    22591: 'dish',        # Pad Thai with shrimp - missed, no "pad thai" keyword
    22335: 'dish',        # stir-fried pumpkin with egg
})
# --- batch 4 (rows 452-601) ---
OVERRIDES.update({
    22062: 'ingredient',  # curry paste (green) - condiment, not a dish itself
    22050: 'ingredient',  # curry paste (red spicy)
    22061: 'ingredient',  # curry paste (red)
    22575: 'dish',        # coffee pudding - ready-to-eat dessert
    22552: 'dish',        # custard pudding
    22576: 'dish',        # young coconut pudding
    22197: 'ingredient',  # plain wholewheat bread loaf
    22457: 'dish',        # mashed potatoes - prepared side
    22677: 'dish',        # mashed potatoes KFC
    22218: 'dish',        # stir-fried whole wheat ramen w/ chicken breast - missed "ผัด"/stir-fry
    22794: 'dish',        # mushroom risotto - complete dish
    22577: 'dish',        # beef lasagna - complete dish
    22490: 'dish',        # tofu larb - ลาบ is a dish
    22418: 'ingredient',  # canned lychees - just fruit in syrup, not a dish
    22451: 'dish',        # mochi ice cream - ready-to-eat dessert
    22252: 'dish',        # deep fried pork loin - ready-to-eat
    22222: 'dish',        # stir-fried spicy pork with cowpeas (ผัดพริกแกง)
    22304: 'dish',        # grilled chicken fillet - ready-to-eat protein
    22483: 'dish',        # sago pork dumpling (สาคูไส้หมู)
    22363: 'dish',        # beefsteak - cooked dish
})
# --- batch 5 (rows 602-751) ---
OVERRIDES.update({
    22268: 'ingredient',  # dried shredded pork - topping/floss, not a dish
    21861: 'dish',        # braised pork spareribs, cooked
    21848: 'dish',        # deep fried pork
    21796: 'dish',        # broiled pork tenderloin, cooked ready-to-eat
    21807: 'dish',        # ground pork, cooked crumbles
    21808: 'dish',        # ground pork, cooked pan-broiled
    22795: 'dish',        # Dongpo pork - braised pork dish
    22585: 'dish',        # boiled pork - Thai ready-to-eat dish
    22594: 'dish',        # Namtok pork - Thai spicy salad dish
    22662: 'dish',        # roast pork
    22469: 'dish',        # baked sweet pork snack (หมูสวรรค์)
    22067: 'dish',        # Thai sweet pork
    22387: 'dish',        # baked egg custard dessert
    22403: 'dish',        # steamed chicken curry (hor mok style)
    22783: 'dish',        # chicken breast with teriyaki sauce
    22734: 'dish',        # steamed chicken breast, chili & lime, flavored RTE
    22219: 'dish',        # CP Delight tender chicken breast, ready-to-eat snack
    22172: 'dish',        # 7-11 chicken chilli, RTE snack
    22178: 'dish',        # CP Delight tender chicken breast RTE
    22173: 'dish',        # CP Delight tender chicken breast with chilli, RTE
    22671: 'dish',        # garlic & chilli tender chicken breast RTE
    22430: 'dish',        # tender chicken breast garlic & pepper CP RTE
    22323: 'dish',        # lemon yogurt tender chicken breast RTE
    22180: 'dish',        # black pepper chicken breast RTE snack
    22217: 'dish',        # grilled chicken breast RTE
    22790: 'dish',        # Ossobuco - braised veal dish
    22443: 'dish',        # Oishi Gyoza - dumpling
    22214: 'dish',        # Oishi Gyoza riceberry flour - dumpling
    22312: 'dish',        # keto chocolate cheese cake
    22419: 'ingredient',  # canned rambutan stuffed w/ pineapple - just canned fruit, not a dish
    22204: 'dish',        # tao huay (soybean milk curd) - ready-to-eat Thai dessert
})
# --- batch 6 (rows 752-901) ---
OVERRIDES.update({
    21900: 'dish',        # prime rib, cooked roasted
    22297: 'dish',        # CP grilled chicken steak burger
    22520: 'dish',        # pork cheese burger
    22320: 'dish',        # whole wheat spicy chicken burger
    22317: 'dish',        # spiced duck (phalo) - braised dish
    22698: 'dish',        # Yen Ta Fo Tom Yum - noodle soup dish
    # plain noodles (raw/cooked, no sauce/prep) mis-tagged dish by generic "noodle" keyword match
    21791: 'ingredient',  # instant Mama noodles, dry
    21984: 'ingredient',  # somen, cooked, plain
    21985: 'ingredient',  # somen, dry
    22397: 'ingredient',  # rice noodle strip, dried
    22398: 'ingredient',  # rice noodle strip, fresh
    22365: 'ingredient',  # plain noodles
    21981: 'ingredient',  # egg noodles, dry
    21980: 'ingredient',  # egg noodles, cooked plain
    22069: 'ingredient',  # rice vermicelli, plain
    21982: 'ingredient',  # soba, cooked plain
    21983: 'ingredient',  # soba, dry
    22017: 'ingredient',  # small rice noodle, dry
    22016: 'ingredient',  # small rice noodle, cooked plain
    22329: 'ingredient',  # kelp noodles, plain
    22071: 'ingredient',  # wide rice noodle, fresh, plain
    21978: 'ingredient',  # canned straw mushroom - just an ingredient
    22141: 'ingredient',  # plain sliced wholewheat bread
    22471: 'dish',        # eclair - filled pastry dessert
    22296: 'dish',        # tuna sandwich farmhouse
    22781: 'dish',        # shredded pork bologna sandwich
    21840: 'ingredient',  # bread flour - raw baking ingredient, not bread itself
    21841: 'ingredient',  # cake flour - raw baking ingredient
    21971: 'dish',        # McDonald's Big Mac - complete fast food dish
    22274: 'dish',        # oat congee - ready-to-eat porridge dish
    22712: 'dish',        # pork congee EZYGO
    22431: 'dish',        # pork congee Easy Go
    22472: 'dish',        # mushroom pork congee Tesco
})
# --- batch 7 (rows 902-1021, final) ---
OVERRIDES.update({
    22581: 'dish',        # dorayaki filled with custard cream
    22452: 'dish',        # mochi cream matcha strawberry
    22467: 'dish',        # mochi choo cream
    22227: 'dish',        # roti with sweetened condensed milk (same as 22390)
    22691: 'ingredient',  # Lotus snack chips, "noodle flavour" - it's a flavored chip snack, not a dish
    21924: 'dish',        # chicken drumstick, roasted, meat only, cooked
    21923: 'dish',        # chicken drumstick, roasted, meat+skin, cooked
    21929: 'dish',        # chicken, roasted, meat+skin, cooked
    21926: 'dish',        # chicken thigh, roasted, meat only, cooked
    21925: 'dish',        # chicken thigh, roasted, meat+skin, cooked
    21918: 'dish',        # chicken breast, cooked/roasted, meat+skin
    21788: 'dish',        # chicken breast, skinless, cooked - ready to eat
    21921: 'dish',        # chicken breast, meat only, cooked roasted
    21857: 'dish',        # chicken, roasted, dark meat
    21856: 'dish',        # chicken, light meat, roasted
    22434: 'dish',        # kai jo (Thai fried chicken patty) with chili
    22523: 'dish',        # kai jo - Thai fried chicken roll dish
    22788: 'dish',        # Samgyetang - Korean ginseng chicken soup
    22456: 'dish',        # KFC chicken pop - RTE fried snack
    22557: 'dish',        # stir-fried chicken with southern curry paste
    21947: 'dish',        # scrambled egg - cooked ready-to-eat
    21946: 'dish',        # poached egg - cooked ready-to-eat
    21945: 'dish',        # omelet - cooked dish
    22147: 'dish',        # steamed egg cup w/ kurobuta pork, CP - RTE convenience dish
    22532: 'dish',        # ice cream (Magnum almond)
    22077: 'dish',        # ice cream (coconut milk)
    21851: 'dish',        # ice cream (chocolate)
    21963: 'dish',        # ice cream (soft serve chocolate)
    21950: 'dish',        # ice cream (soft serve vanilla)
    21850: 'dish',        # ice cream (vanilla)
    21852: 'dish',        # ice cream (strawberry)
    22024: 'dish',        # sherbet (orange)
    22531: 'dish',        # ice cream (mixed)
    22530: 'dish',        # ice cream (green tea)
    22529: 'dish',        # ice cream (vanilla, Wall)
    22533: 'dish',        # ice cream (Oreo)
})
# --- thaifcd T group corrections (sauces/condiments/stocks mistagged dish, and
#     savory snack items - chips, roasted/salted nuts&seeds, jerky, rice crackers,
#     plain bread - mistagged dish just because group T defaults to dish) ---
OVERRIDES.update({
    21384: 'ingredient',  # jarred spaghetti sauce
    21398: 'ingredient',  # chicken bone soup/stock base
    21399: 'ingredient',  # pork leg soup/stock base
    21414: 'ingredient',  # jarred spaghetti sauce, various
    21652: 'ingredient',  # peanut curry sauce topping for khanom jeen (not the full dish)
    21653: 'ingredient',  # nam-ya curry sauce topping (not the full dish)
    21655: 'ingredient',  # jarred spaghetti sauce, various flavours
    21660: 'ingredient',  # topping/sauce for khao tang, not standalone
    21640: 'ingredient',  # plain sandwich bread loaf
    21641: 'ingredient',  # plain milk bun
    21642: 'ingredient',  # plain sweet bun
    21643: 'ingredient',  # plain wholewheat bread
    21637: 'ingredient',  # crispy bread crackers, savory snack
    21638: 'ingredient',  # breadstick snack
    21596: 'ingredient', 21597: 'ingredient', 21598: 'ingredient', 21599: 'ingredient', 21595: 'ingredient',  # peanuts, roasted/coated snack
    21600: 'ingredient', 21601: 'ingredient', 21602: 'ingredient', 21603: 'ingredient',  # sunflower seeds snack
    21606: 'ingredient', 21607: 'ingredient',  # cocktail nuts snack
    21624: 'ingredient', 21625: 'ingredient',  # cashew nuts snack
    21632: 'ingredient', 21633: 'ingredient', 21634: 'ingredient', 21635: 'ingredient',  # macadamia snack
    21618: 'ingredient',  # pistachio snack
    21636: 'ingredient',  # almond snack
    21592: 'ingredient', 21593: 'ingredient', 21594: 'ingredient',  # broad bean / sugar pea fried snack
    21571: 'ingredient',  # jackfruit crisps
    21604: 'ingredient', 21605: 'ingredient',  # durian crisps
    21615: 'ingredient',  # taro crisps
    21619: 'ingredient',  # pumpkin crisps
    21627: 'ingredient', 21628: 'ingredient', 21629: 'ingredient',  # potato chips
    21583: 'ingredient',  # rice chip snack
    21584: 'ingredient', 21585: 'ingredient', 21586: 'ingredient',  # corn snack
    21577: 'ingredient', 21578: 'ingredient', 21579: 'ingredient', 21580: 'ingredient', 21581: 'ingredient', 21582: 'ingredient',  # khaotan rice cracker snack
    21608: 'ingredient', 21609: 'ingredient', 21610: 'ingredient',  # seasoned fish/squid jerky snack
    21630: 'ingredient',  # grilled cassava ball snack
    21590: 'ingredient',  # sesame/sunflower honey snack bar
})
# --- thaifcd non-S/T groups: found real prepared dishes hiding in "ingredient" default ---
OVERRIDES.update({
    20985: 'dish',  # oyster, stir fried - standalone Thai dish
    20990: 'dish',  # clam, stir fried - standalone Thai dish
})
