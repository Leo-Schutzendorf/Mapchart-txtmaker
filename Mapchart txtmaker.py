import requests
from bs4 import BeautifulSoup
import pandas as pd

#Ask for year
year = input("Enter the year of the election (e.g., 1988): ")

states = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware", "Florida",
          "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
          "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New_Hampshire",
          "New_Jersey", "New_Mexico", "New_York", "North_Carolina", "North_Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
          "Rhode_Island", "South_Carolina", "South_Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington_(State)",
          "West_Virginia", "Wisconsin", "Wyoming"]

postalCodes = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
               "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
               "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
               "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New_Hampshire": "NH", "New_Jersey": "NJ", "New_Mexico": "NM", "New_York": "NY", "North_Carolina": "NC",
               "North_Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode_Island": "RI", "South_Carolina": "SC", "South_Dakota": "SD", "Tennessee": "TN",
               "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington_(State)": "WA", "West_Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
for state in states:
    print("Processing " + state + "...")#For the user to know that the program is working and not frozen. Also, Texas and Virginia have a shit ton of counties, so this is helpful for knowing the progress.
    if state == "Alaska":
        continue

    url = "https://en.wikipedia.org/wiki/" + year + "_United_States_presidential_election_in_" + state

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, "html.parser")

    # Find the table that contains "County"
    tables = soup.find_all('table', class_=lambda c: c and 'wikitable' in c)

    table = None
    for t in tables:
        if "County" in t.get_text() or "Parish" in t.get_text():
            table = t
            break

    rows = []
    for tr in table.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
        if cells:
            rows.append(cells)
    

    """Get the state winner and runner-up from the first two rows of the table. The first row contains the winner, and the second row contains the runner-up. If neither row contains "Republican"
    or "Democrat", then we can assume that a third party candidate was the runner-up."""

    header = rows
    if "Republican" in header[1]:
        state_winner = "Republican"
        RepLoc = 1
    if "Democrat" in header[1]:
        state_winner = "Democrat"
        DemLoc = 1
    if "Republican" not in header[1] and "Democrat" not in header[1]:
        state_winner = "Third party"
        ThirdpartyLoc = 1

    if "Republican" in header[2]:
        state_runner_up = "Republican"
        RepLoc = 2
    if "Democrat" in header[2]:
        state_runner_up = "Democrat"
        DemLoc = 2
    if "Republican" not in header[2] and "Democrat" not in header[2]:
        state_runner_up = "Third party"
        ThirdpartyLoc = 2

    if "Republican" in header[3]:
        state_third_place = "Republican"
        RepLoc = 3
    if "Democrat" in header[3]:
        state_third_place = "Democrat"
        DemLoc = 3
    if "Republican" not in header[3] and "Democrat" not in header[3]:
        state_third_place = "Third party"
        ThirdpartyLoc = 3

    Republican_30_40 = []
    Democrat_30_40 = []
    Third_party_30_40 = []
    Republican_40_50 = []
    Democrat_40_50 = []
    Third_party_40_50 = []
    Republican_50_60 = []
    Democrat_50_60 = []
    Third_party_50_60 = []
    Republican_60_70 = []
    Democrat_60_70 = []
    Third_party_60_70 = []
    Republican_70_80 = []
    Democrat_70_80 = []
    Third_party_70_80 = []
    Republican_80_90 = []
    Democrat_80_90 = []
    Third_party_80_90 = []
    Republican_90_100 = []
    Democrat_90_100 = []
    Third_party_90_100 = []
    
    """
    Uncomment the following lines to print county data for debugging purposes. The first row contains the header, and the second row contains the state winner and runner-up. The county data
    starts from the third row.

    for i, row in enumerate(rows):
        print(f"Row {i} (len={len(row)}): {row}")"""
    
    for row in rows[2:]:  # Skip header rows.  Also, the county name is in row[0].
        if int(row[1].replace(',', ''))>=int(row[3].replace(',', '')) and int(row[1].replace(',', ''))>=int(row[5].replace(',', '')):
            county_winner = state_winner
        if int(row[3].replace(',', ''))>=int(row[1].replace(',', '')) and int(row[3].replace(',', ''))>=int(row[5].replace(',', '')):
            county_winner = state_runner_up

        """Assign the county winner to a list based on their percentage of the vote."""
        if county_winner == "Republican":
            if float(row[RepLoc].replace('%', ''))>=30 and float(row[RepLoc].replace('%', ''))<40:
                Republican_30_40.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[RepLoc].replace('%', ''))>=40 and float(row[RepLoc].replace('%', ''))<50:
                Republican_40_50.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[RepLoc].replace('%', ''))>=50 and float(row[RepLoc].replace('%', ''))<60:
                Republican_50_60.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[RepLoc].replace('%', ''))>=60 and float(row[RepLoc].replace('%', ''))<70:
                Republican_60_70.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[RepLoc].replace('%', ''))>=70 and float(row[RepLoc].replace('%', ''))<80:
                Republican_70_80.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[RepLoc].replace('%', ''))>=80 and float(row[RepLoc].replace('%', ''))<90:
                Republican_80_90.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[RepLoc].replace('%', ''))>=90 and float(row[RepLoc].replace('%', ''))<=100:
                Republican_90_100.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")

        if county_winner == "Democrat":
            if float(row[DemLoc].replace('%', ''))>=30 and float(row[DemLoc].replace('%', ''))<40:
                Democrat_30_40.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[DemLoc].replace('%', ''))>=40 and float(row[DemLoc].replace('%', ''))<50:
                Democrat_40_50.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[DemLoc].replace('%', ''))>=50 and float(row[DemLoc].replace('%', ''))<60:
                Democrat_50_60.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[DemLoc].replace('%', ''))>=60 and float(row[DemLoc].replace('%', ''))<70:
                Democrat_60_70.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[DemLoc].replace('%', ''))>=70 and float(row[DemLoc].replace('%', ''))<80:
                Democrat_70_80.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[DemLoc].replace('%', ''))>=80 and float(row[DemLoc].replace('%', ''))<90:
                Democrat_80_90.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[DemLoc].replace('%', ''))>=90 and float(row[DemLoc].replace('%', ''))<=100:
                Democrat_90_100.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
        
        if county_winner == "Third party":
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=30 and float(row[ThirdpartyLoc+1].replace('%', ''))<40:
                Third_party_30_40.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=40 and float(row[ThirdpartyLoc+1].replace('%', ''))<50:
                Third_party_40_50.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=50 and float(row[ThirdpartyLoc+1].replace('%', ''))<60:
                Third_party_50_60.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=60 and float(row[ThirdpartyLoc+1].replace('%', ''))<70:
                Third_party_60_70.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=70 and float(row[ThirdpartyLoc+1].replace('%', ''))<80:
                Third_party_70_80.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=80 and float(row[ThirdpartyLoc+1].replace('%', ''))<90:
                Third_party_80_90.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
            if float(row[ThirdpartyLoc+1].replace('%', ''))>=90 and float(row[ThirdpartyLoc+1].replace('%', ''))<=100:
                Third_party_90_100.append("\""+str(row[0])+"__"+postalCodes[state]+"\"")
    
    
    # write results to txt file
    with open("output.txt", "w", encoding="utf-8") as f:
        f.write("\{\"groups\":\{\"\#d3e7ff\":\{\"label\":\"Democratic 30-40\",\"paths\":\n[")
        for county in Democrat_30_40:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#b9d7ff\":\{\"label\":\"Democratic 40-50\",\"paths\":\n[")
        for county in Democrat_40_50:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#86b6f2\":\{\"label\":\"Democratic 50-60\",\"paths\":\n[")
        for county in Democrat_50_60:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#4389e3\":\{\"label\":\"Democratic 60-70\",\"paths\":\n[")
        for county in Democrat_60_70:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#1666cb\":\{\"label\":\"Democratic 70-80\",\"paths\":\n[")
        for county in Democrat_70_80:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#0645b4\":\{\"label\":\"Democratic 80-90\",\"paths\":\n[")
        for county in Democrat_80_90:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#0047b9\":\{\"label\":\"Democratic 90-100\",\"paths\":\n[")
        for county in Democrat_90_100:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#ffccd0\":\{\"label\":\"Republican 30-40\",\"paths\":\n[")
        for county in Republican_30_40:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#f2b3be\":\{\"label\":\"Republican 40-50\",\"paths\":\n[")
        for county in Republican_40_50:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#e27f90\":\{\"label\":\"Republican 50-60\",\"paths\":\n[")
        for county in Republican_50_60:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#cc2f4a\":\{\"label\":\"Republican 60-70\",\"paths\":\n[")
        for county in Republican_60_70:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#d40000\":\{\"label\":\"Republican 70-80\",\"paths\":\n[")
        for county in Republican_70_80:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#aa0000\":\{\"label\":\"Republican 80-90\",\"paths\":\n[")
        for county in Republican_80_90:
            f.write(county+",")
        f.write("]},")
        f.write("\n\"\#800000\":\{\"label\":\"Republican 90-100\",\"paths\":\n[")
        for county in Republican_90_100:
            f.write(county+",")
        f.write("]}")