import geopandas as gpd
import pandas as pd
from pysal.weights import Contiguity
import matplotlib.pyplot as plt
from us import states # for helping with FIPS codes
import os
import urllib
import zipfile


# Runtime settings
contiguityType = 'rook' # queen includes corner-only touches; rook excludes corner-only touches
cellularUnit = 'tract' # use Census 'tract'; possible extension for 'block' later
holeFiller = True # should growing districts absorb any holes or exclaves which they create
debugMode = False



def chooseState():

	if debugMode:
		processState('NH',5) # Testing mode does NH with 5 districts

	else:

		# User input: choose to run all states or custom single state
		modeChoice = raw_input('How would you like to run?\n1) Run all states using 2010 House apportionments\n2) Choose a single state\n')

		# Run all states mode
		if modeChoice == '1':
			
			# 2010 apportionments of US House districts
			districtCounts = (('AL', 7), ('AK', 1), ('AZ', 9), ('AR', 4), ('CA', 53), ('CO', 7), ('CT', 5), ('DE', 1), ('FL', 27), ('GA', 14), ('HI', 2), ('ID', 2), ('IL', 18), ('IN', 9), ('IA', 4), ('KS', 4), ('KY', 6), ('LA', 6), ('ME', 2), ('MD', 8), ('MA', 9), ('MI', 14), ('MN', 8), ('MS', 4), ('MO', 8), ('MT', 1), ('NE', 3), ('NV', 4), ('NH', 2), ('NJ', 12), ('NM', 3), ('NY', 27), ('NC', 13), ('ND', 1), ('OH', 16), ('OK', 5), ('OR', 5), ('PA', 18), ('RI', 2), ('SC', 7), ('SD', 1), ('TN', 9), ('TX', 36), ('UT', 4), ('VT', 1), ('VA', 11), ('WA', 10), ('WV', 3), ('WI', 8), ('WY', 1))
			
			# Run processState on each state, skipping states with 1 district
			for state in districtCounts:
				if state[1] > 1:
					processState(*state)
				else:
					print "Skipping single-district state"

		# Run single state mode
		elif modeChoice == '2':
			
			# User input: state to process
			state = raw_input('Which state would you like to process? (Two letter abbreviation) ')
			if not states.lookup(state):
				print "Invalid state entered!"
				exit()

			# User input: number of districts to create
			maxDistricts = raw_input('Number of districts to create? ')
			try:
				int(maxDistricts)
			except ValueError:
				print "Invalid number of districts chosen!"
				exit()
			else:
				maxDistricts = int(maxDistricts)

			# Run processState on selected state with selected number of districts
			processState(state,maxDistricts)

		else:
			print "Invalid run mode chosen!"
			exit()


def processState(state,maxDistricts):


	def getNeighbors(d):
		allNeighbors = [adjacencyMatrix.neighbors[x] for x in d]
		allNeighbors = [m for n in allNeighbors for m in n if m not in assignedList]
		return list(set(allNeighbors))


	fips = states.lookup(state).fips
	print "Beginning districting on %s (FIPS %s) with %s districts" % (state,fips,maxDistricts)

	# Check if geometry file exists; download if not
	geomDir = 'data-raw/%s/geometry/' % cellularUnit
	geomFile = ('%stl_2010_%s_tract10.shp')%(geomDir,fips)

	if os.path.isfile(geomFile):
		print "Found geometry file"
	else:
		if not os.path.exists(geomDir): os.makedirs(geomDir)
		print "Acquiring geometry file from Census"
		urllib.urlretrieve( states.lookup(state).shapefile_urls('tract') , ('%s%s.zip')%(geomDir,state))
		with zipfile.ZipFile(('%s%s.zip')%(geomDir,state)) as zip:
			zip.extractall(geomDir)
		os.remove(('%s%s.zip')%(geomDir,state))

	# Check if gazeteer file exists; download if not
	gazDir = 'data-raw/%s/gazetteer/' % cellularUnit
	gazFile = ('%scensus_tracts_list_%s.txt')%(gazDir,fips)

	if os.path.isfile(gazFile):
		print "Found gazetteer file"
	else:
		if not os.path.exists(gazDir): os.makedirs(gazDir)
		print "Acquiring gazeteer file from Census"
		urllib.urlretrieve( ('http://www2.census.gov/geo/docs/maps-data/data/gazetteer/census_tracts_list_%s.txt')%(fips) , ('%scensus_tracts_list_%s.txt')%(gazDir,fips))


	# Read in the geometry file with GeoPandas
	try:
		geometry = gpd.read_file(geomFile)
		geometry = geometry[['GEOID10','geometry']] # Lose everything except FIPS code and geometry
		print "Successfully read geometry file"
	except:
		print "Problem reading geometry file"
		exit()


	# Read in the gazeteer file with Pandas
	try:
		gazetteer = pd.read_table(gazFile,dtype={'GEOID':'object'})
		gazetteer = gazetteer[['GEOID','POP10','ALAND']] # Lose everything except FIPS code, pop, land area
		gazetteer['density'] = gazetteer['POP10']/gazetteer['ALAND'] # Compute density across all tracts
		print "Successfully read gazetteer file"
	except:
		print "Problem reading gazetteer file"
		exit()

	# Create a joined data frame
	dataFrame = geometry.merge(gazetteer, left_on='GEOID10', right_on='GEOID')
	dataFrame['district'] = 0 # New blank variable for district assignment

	if holeFiller:
		fullShape = dataFrame.unary_union	

	# Create an adjanceny matrix using pysal
	if contiguityType == 'rook':
		adjacencyFunction = Contiguity.Rook.from_dataframe
	elif contiguityType == 'queen':
		adjacencyFunction = Contiguity.Queen.from_dataframe
	else:
		print 'Invalid contiguity type set!'
		exit()
	
	adjacencyMatrix = adjacencyFunction(geometry)
	print "Adjacency matrix built"

	popThreshold = dataFrame['POP10'].sum() / maxDistricts # How many people should be in each district
	
	assignedList = [] # List to hold indices all assigned tracts, for speed

	for d in range(1,maxDistricts+1):

		districtPop = 0
		districtMembers = [] # List to hold indices of tracts assigned to this district, for speed
		seed = dataFrame[dataFrame['district']==0]['density'].idxmax() # Find the densest unassigned

		districtPop = districtPop + dataFrame['POP10'][seed]
		dataFrame.set_value(seed,'district',d)
		districtMembers.append(seed)
		assignedList.append(seed)

		print "Beginning district %d, seeding with %s %s, running population %d" % (d,cellularUnit,dataFrame['GEOID10'][seed],districtPop)

		while districtPop < popThreshold:
			possibleNeighbors = getNeighbors(districtMembers)
			if len(possibleNeighbors) == 0:
				print "No possible neighbors to add!"
				break
			bestNeighbor = dataFrame.iloc[possibleNeighbors]['density'].idxmax()

			
			districtPop = districtPop + dataFrame['POP10'][bestNeighbor]
			dataFrame.set_value(bestNeighbor,'district',d)
			districtMembers.append(bestNeighbor)
			assignedList.append(bestNeighbor)

			print "Adding %s, running population %d" % (dataFrame['GEOID10'][bestNeighbor],districtPop)

			if holeFiller:
				fullShape = fullShape.difference(dataFrame.iloc[bestNeighbor].geometry)
				if fullShape.geom_type == 'MultiPolygon':
					print "A hole or exclave has been created!"

					for part in fullShape:

						partTracts = dataFrame[dataFrame.geometry.within(part)].index.tolist()

						partPop = dataFrame.iloc[partTracts].POP10.sum()

						if partPop < popThreshold - districtPop:
							dataFrame.loc[partTracts,"district"] = d
							districtPop = districtPop + partPop
							assignedList.extend(partTracts)
							districtMembers.extend(partTracts)

							fullShape = fullShape.difference(part)

							print "Filled a hole or exclave"






	# Build a choropleth map
	p = dataFrame.plot(column='district',categorical=True,legend=True)
	plt.show()




if __name__ == '__main__':
	chooseState()
