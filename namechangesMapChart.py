import requests
import json
import re
from bs4 import BeautifulSoup
def namechanges(countyName, state, year):
    """Normalize county name for MapChart: fix certain words.  If statements are for when the change applies to a county name in only one state."""
    countyName = countyName.replace("\'", "_")

    #-------- Alaska ---------
    countyName = countyName.replace(" City and", "").replace(" Borough", "").replace(" Census Area", "").replace(" Municipality", "")
    countyName = countyName.replace("Southeast Fairbanks", "SE_Fairbanks")
    
    countyName = countyName.replace("Planning Region", "") #Connecticut

    if state == "Florida":
        countyName = countyName.replace("De Soto", "DeSoto")
        countyName = countyName.replace("Miami-Dade", "Miami_Dade")
        if year <= "1988":
            countyName = countyName.replace("Dade", "Miami_Dade")

    countyName = countyName.replace("Kauaʻi", "Kauai")# Hawaii

    if state == "Illinois":
        countyName = countyName.replace("LaSalle", "La_Salle").replace("DeWitt", "De_Witt")# Illinois
    
    countyName = countyName.replace("LaRue", "Larue")# Kentucky

    if state == "Louisiana":
        countyName = countyName.replace("DeSoto", "De_Soto")

    if state == "Maryland":
        if countyName == "Baltimore":
            countyName = "Baltimore_County"
        if "Mary" in countyName and "St" in countyName:
            countyName = "St_Mary_s" 

    if state == "Mississippi":
        countyName = countyName.replace("De Soto", "DeSoto")

    countyName = countyName.replace("Ste. Genevieve", "Sainte_Genevieve")#Missouri

    if state == "Missouri":
        if countyName == "St. Louis":
            countyName = "St__Louis_Co_"
        if countyName == "St. Louis City":
            countyName = "St__Louis"
    countyName = countyName.replace("Ormsby", "Carson_City")# Nevada
    countyName = countyName.replace("Coös", "Coos")# New Hampshire
    countyName = countyName.replace("Doña Ana", "Dona_Ana")# New Mexico
    countyName = countyName.replace("LeFlore", "Le_Flore")# Oklahoma
    if state == "South_Dakota":
        countyName = countyName.replace("Shannon", "Oglala_Lakota")

    #-------- Virginia ---------
    if state == "Virginia":
        countyName = countyName.replace(" County", "_Co_")
        countyName = countyName.replace("Bedford", "Bedford_Co_")

        if countyName == "Fairfax":
            countyName = "Fairfax_Co_"
        
        if "Franklin" in countyName and "City" not in countyName:
            countyName = "Franklin_Co_"

        if countyName == "Richmond":
            countyName = "Richmond_Co_"

        if countyName == "Roanoke":
            countyName = "Roanoke_Co_"

        if "City" in countyName and "James City" not in countyName and "Charles" not in countyName:
            countyName = countyName.replace(" City", "")
    return countyName