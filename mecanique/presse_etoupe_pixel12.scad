// Presse-étoupe pour pixel LED WS2811 « bullet » 12 mm — panneau bois / MDF 3 à 6 mm
// Armoire à clés connectée — Tomacbe — licence MIT
//
// 3 pièces, comme un vrai presse-étoupe :
//   corps        : collerette visible à l'avant + tige filetée qui traverse le panneau,
//                  terminée à l'arrière par une PINCE (4 lamelles)
//   contre-ecrou : serre le corps contre le panneau (côté arrière)
//   ecrou-chapeau: se visse sur la pince ; son cône intérieur resserre les lamelles sur le pixel
//
// Montage (le pixel reste sur sa chaîne, rien à démonter) :
//   1. percer le panneau au diamètre « perçage » (18 mm par défaut) ;
//   2. enfiler l'écrou-chapeau puis le contre-écrou sur le pixel PAR LE DÔME (ils glissent vers les fils) ;
//   3. passer le corps dans le trou par l'avant du panneau ;
//   4. pousser le pixel par l'arrière dans le corps, dôme vers l'avant, jusqu'à la butée ;
//   5. visser le contre-écrou contre le panneau, puis l'écrou-chapeau sur la pince : le pixel est serré.
//
// Impression : PETG (ou PLA), corps collerette sur le plateau, écrous à plat, sans support, couche 0,2 mm.

/* [Pièce] */
piece = "plateau";          // [corps, contre_ecrou, ecrou_chapeau, plateau, coupe_assemblage]

/* [Pixel — mesures au pied à coulisse] */
pixel_d = 12.0;            // diamètre du corps du pixel
jeu_pixel = 0.4;           // jeu dans l'alésage
butee = true;              // lèvre à l'avant qui arrête le pixel (le dôme se voit par la fenêtre)
fenetre_d = 10.5;          // diamètre de la fenêtre avant (si butée)

/* [Panneau] */
panneau_max = 6;           // épaisseur maxi du panneau

/* [Corps] */
collerette_h = 2.5;
collerette_deb = 4;        // débord de la collerette autour du perçage
paroi = 1.6;
pince_l = 4;               // longueur de la zone de serrage (bout des lamelles)
nb_lamelles = 4;
fente_lamelles = 1.5;

/* [Filetage] */
pas = 2.0;
prof_filet = 1.0;
jeu_filet = 0.35;          // augmenter si trop serré

/* [Écrous] */
plats = 24;                // dimension sur plats des écrous
contre_ecrou_h = 4;
chapeau_filet_h = 5;       // partie filetée de l'écrou-chapeau
serrage = 0.5;             // resserrement radial des lamelles en fin de vissage

$fn = 96;

// ------------------------------------------------------------------ dimensions dérivées
alesage = pixel_d + jeu_pixel;
filet_d = ceil(alesage + 2 * paroi + 2 * prof_filet);
percage = filet_d;
filet_l = panneau_max + contre_ecrou_h + chapeau_filet_h;
tige_l = filet_l + pince_l;
corps_h = collerette_h + tige_l;
collerette_d = percage + 2 * collerette_deb;
r_pince = filet_d / 2 - prof_filet;                 // rayon extérieur du bout des lamelles
chapeau_h = chapeau_filet_h + pince_l + 1.2;

echo(str("PERÇAGE ", percage, " mm | filet ", filet_d, " x ", pas, " | corps ", corps_h,
         " mm | écrous ", plats, " sur plats"));

module filet(d, l, jeu = 0) {
    linear_extrude(height = l, twist = -360 * l / pas, slices = ceil(l / pas * 36), convexity = 6)
        translate([prof_filet / 2, 0]) circle(d = d - prof_filet + 2 * jeu);
}

module hexagone(h) { cylinder(d = plats / cos(30), h = h, $fn = 6); }

// ------------------------------------------------------------------ corps
module corps() {
    difference() {
        union() {
            // collerette visible avec petit chanfrein
            cylinder(d1 = collerette_d - 1, d2 = collerette_d, h = 0.5);
            translate([0, 0, 0.5]) cylinder(d = collerette_d, h = collerette_h - 0.5);
            // tige filetée
            translate([0, 0, collerette_h - 0.01]) filet(filet_d, filet_l + 0.01);
            // bout de pince lisse, légèrement conique pour l'entrée de l'écrou-chapeau
            translate([0, 0, collerette_h + filet_l])
                cylinder(r1 = r_pince, r2 = r_pince - 0.3, h = pince_l);
        }
        // alésage du pixel
        translate([0, 0, butee ? 1.0 : -1]) cylinder(d = alesage, h = corps_h + 2);
        if (butee) translate([0, 0, -1]) cylinder(d = fenetre_d, h = 3);
        // lamelles de la pince : fentes à partir de la zone du contre-écrou
        for (i = [0 : nb_lamelles - 1])
            rotate([0, 0, i * 360 / nb_lamelles + 45])
                translate([0, -fente_lamelles / 2, collerette_h + panneau_max + contre_ecrou_h])
                    cube([filet_d, fente_lamelles, tige_l]);
        // chanfrein d'entrée arrière
        translate([0, 0, corps_h - 0.8]) cylinder(d1 = alesage, d2 = alesage + 1.2, h = 0.81);
    }
}

// ------------------------------------------------------------------ contre-écrou
module contre_ecrou() {
    difference() {
        hexagone(contre_ecrou_h);
        translate([0, 0, -0.01]) filet(filet_d, contre_ecrou_h + 0.02, jeu_filet);
        translate([0, 0, -0.01]) cylinder(d1 = filet_d + 1, d2 = filet_d - 1, h = 1);
        translate([0, 0, contre_ecrou_h - 0.99]) cylinder(d1 = filet_d - 1, d2 = filet_d + 1, h = 1);
    }
}

// ------------------------------------------------------------------ écrou-chapeau (cône de serrage)
module ecrou_chapeau() {
    difference() {
        union() {
            hexagone(chapeau_filet_h + pince_l);
            translate([0, 0, chapeau_filet_h + pince_l - 0.01])
                cylinder(d1 = plats, d2 = plats - 3, h = 1.2);
        }
        translate([0, 0, -0.01]) filet(filet_d, chapeau_filet_h + 0.02, jeu_filet);
        translate([0, 0, -0.01]) cylinder(d1 = filet_d + 1, d2 = filet_d - 1, h = 1);
        // cône intérieur : se referme vers le haut pour resserrer les lamelles
        translate([0, 0, chapeau_filet_h - 0.01])
            cylinder(r1 = r_pince + 0.2, r2 = r_pince - 0.3 - serrage, h = pince_l + 0.02);
        // passage du pixel (le chapeau s'enfile par le dôme)
        cylinder(d = alesage + 0.6, h = chapeau_h + 2);
    }
}

// ------------------------------------------------------------------ sortie
if (piece == "corps") corps();
else if (piece == "contre_ecrou") contre_ecrou();
else if (piece == "ecrou_chapeau") ecrou_chapeau();
else if (piece == "plateau") {
    corps();
    translate([collerette_d / 2 + plats / 2 + 5, 0, 0]) contre_ecrou();
    translate([collerette_d / 2 + plats * 1.5 + 12, 0, 0]) ecrou_chapeau();
} else if (piece == "coupe_assemblage") {
    difference() {
        union() {
            color("white") corps();
            color("burlywood", 0.7) translate([0, 0, collerette_h]) difference() {
                translate([-25, -25, 0]) cube([50, 50, panneau_max]);
                translate([0, 0, -1]) cylinder(d = percage, h = panneau_max + 2);
            }
            color("silver") translate([0, 0, collerette_h + panneau_max]) contre_ecrou();
            color("dimgray") translate([0, 0, collerette_h + panneau_max + contre_ecrou_h + 0.3]) ecrou_chapeau();
            // pixel 12 mm (dôme en butée contre la lèvre avant)
            color("lightcyan", 0.8) translate([0, 0, butee ? 1.0 : -3]) {
                translate([0, 0, 1.5]) cylinder(d = pixel_d, h = 28);
                translate([0, 0, 1.5]) sphere(d = pixel_d) ;
            }
        }
        translate([0, -40, -10]) cube([80, 80, 80]);
    }
}
