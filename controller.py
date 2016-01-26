import model
from flask import Flask
from flask import render_template, request, redirect, url_for, flash, jsonify
import urllib2
from urllib import quote
from math import sqrt
import pandas as pd
from scipy import ndimage as nd
import json
import time
import numpy as np
from numpy.random import random_sample
import os

from numpy import random
import math
# TODO: add wtfworms import wtforms
#Create flask instance
application = Flask(__name__)

# Import environment configuration settings for API
# app.config.from_envvar('BABY_MAKERS_SETTINGS', silent=True)
# API_KEY = app.config['API_KEY']
API_KEY = os.environ['API_KEY']


def get_celeb_score(data, celeb_years, alpha=0.95):
	"""Takes a dict of year:births *for years wanted*, and a list of movie years within
	this range"""
	# NOTE: Check that we have zeros where we should in babyname data
	# NOTE: Are assuming dict of years:births over range we want to consider
	# Convert birth data dict to a pandas Series
	birth_data = pd.Series(data)
	birth_data.sort(inplace=True)
	all_yrs = birth_data.index
	# Differentiate series
	name_diff = pd.Series(np.append(np.diff(birth_data.values),0))
	name_diff.index = all_yrs
	# KDE on values
	kde_vals = nd.filters.gaussian_filter(birth_data.values, sigma=2)
	# Differentiate values smoothed by kde
	kde_diff = pd.Series(np.append(np.diff(kde_vals),0))
	kde_diff.index = all_yrs
	# Get celebs score
	celeb_score = calc_celeb_score(celeb_years, name_diff, kde_diff)
	# Get values for random distribution
	mc_samp = []
	min_yr = min(all_yrs)
	max_yr = max(all_yrs)
	for i in range(10000):
		rand_yrs = get_rand_years(5,min_yr,max_yr)
		mc_samp.append(calc_celeb_score(rand_yrs,name_diff, kde_diff))
	# Generate histogram data:
	wts = np.ones_like(mc_samp)/float(len(mc_samp))
	hist_vals, hist_bins = np.histogram(mc_samp, bins=int(sqrt(len(mc_samp))), weights=wts)
	# Get list of hist vals within given significance
	celeb_pval, percentiles = get_percentile_points(hist_vals, hist_bins, alpha, celeb_score=celeb_score)
	# Return celebrity score, hist_vals, and percentile data
	return celeb_pval, celeb_score, hist_vals.tolist(), hist_bins.tolist(), percentiles.value.tolist()

def calc_celeb_score(celeb_yrs, name_diff, smooth_diff):
	"""Rule for scoring a celebrities years based on derivatives"""
	all_yrs = name_diff.index
	scores_next = [name_diff[yr] - smooth_diff[yr] for yr in celeb_yrs]
	scores_current = [name_diff[x-1] - smooth_diff[x-1] if x in all_yrs+1 else 0 for x in celeb_yrs]
	return max(sum(scores_next), sum(scores_current))

def get_rand_years(n, min_yr, max_yr):
	"""Return n random years from the range [min_year, max_year]"""
	rnd_yr_list = [int(np.ceil((max_yr-min_yr)*random_sample() + min_yr)) \
					for a in range(0,n)]
	return np.array(rnd_yr_list)

def get_percentile_points(hist_vals, hist_bins, percentile_value, celeb_score=None):
	"""Return dataframe of histogram points that fall within given percentile
	with columns 'value' and 'weight'. If passed a celebrity score, also returns
	p-value of that particular celebrities score.
	hist_vals: Result of assignment to a plt.hist instance
	percential_value: The percentile to find"""
	# Create Series of bin values and weights from the histogram (so can sort and retain indices)
	hist_df = pd.DataFrame(zip(hist_bins, hist_vals), columns=['value', 'weight'])
	# Sort the histogram values by weight
	hist_df_sort = hist_df.sort(columns='weight', ascending=False)
	# Get cumulative sum of weights
	hist_df_sort['cumsum'] = hist_df_sort['weight'].cumsum()
	# Get all values for which cumsum falls below percentile value required
	percentile_vals = hist_df_sort['cumsum'][hist_df_sort['weight'] < percentile_value]
	# If passed celebrity score, then also work out and return it's p-value
	if celeb_score:
		sortbyval = hist_df_sort.sort('value')
		max_vals = sortbyval['value'] >= celeb_score
		min_vals = sortbyval['value'] <= celeb_score
		max_idx = sortbyval.ix[max_vals, 'value'].idxmin()
		min_idx = sortbyval.ix[min_vals, 'value'].idxmax()
		# Take average of elements closest to celeb_score
		celeb_pval = sortbyval.ix[min_idx:max_idx, 'cumsum'].mean()
	else:
		celeb_pval = None
	return celeb_pval, hist_df.ix[percentile_vals.index]

def check_str(name):
	#Make sure camel case
	new_name = name.lower().capitalize()
	return new_name

# def get_movie_ids(json_vals):
# 	"""Takes a json page and returns dict with movie names and ids"""
# 	ret_dict = {}
# 	for movie in json_vals['results']:
# 		ret_dict[movie['title']] = [movie['id'], int(movie['release_date'][:4])]
# 	return ret_dict

def get_movie_ids(json_vals):
	"""Takes a json page and returns list of dicts with movie names and ids"""
	ret_list = []
	for movie in json_vals['results']:
		# Only add movie to list if json contains info needed in right format
		if ((len(movie['title'])>0) & (isInt_str(movie['id'])) & (isInt_str(movie['release_date'][:4]))):
			# REMOVE THIS WHEN UPDATE DATABASE!?!?!?
			if (int(movie['release_date'][:4]) <= 2010):
				mov_inf = {'info': {'title': movie['title'], 'm_id': movie['id'], 'release': int(movie['release_date'][:4]), 'poster': None}}
				# Add on poster_path if it exists otherwise leave as None
				if ('poster_path' in movie):
					if (movie['poster_path'] and (len(movie['poster_path'])>0)):
						mov_inf['info']['poster'] = movie['poster_path']
				ret_list.append(mov_inf)
	return ret_list


def isInt_str(v):
	''' Checks if string contains an int'''
	v = str(v).strip()
	return v=='0' or (v if v.find('..') > -1 else v.lstrip('-+').rstrip('0').rstrip('.')).isdigit()

base_url = "http://api.themoviedb.org/3/"

def remove_repeats(movie_dict):
	# Get list of ids in same order as list of movie dics
	id_list = [x['info']['m_id'] for x in movie_dict]

	# Create dict of occurences of each number
	y = np.bincount(id_list)
	ii = np.nonzero(y)[0]
	count_dic = dict(zip(ii,y[ii]))
	del_idx = []
	# Now loop through movie_dict entries, remove if more than one occurences
	for idx, mov in enumerate(movie_dict):
		if count_dic[mov['info']['m_id']] > 1:
			# log entry for delete
			del_idx.append(idx)
			# Reduce counts for this entry
			count_dic[mov['info']['m_id']] -= 1
	# Now delete those entries from list in reverse
	for index in sorted(del_idx, reverse=True):
		del movie_dict[index]

	return movie_dict

# TODO: Upadate to return suggestions if not unique result for name
def get_movieapi_results(full_name):
	"""Takes full name string (not URL encoded) and returns dict of movies"""
	# Convert name to URL encoded string
	# print full_name
	full_name = quote(full_name)
	# print full_name
	name_url = "http://api.themoviedb.org/3/search/person?&api_key="+API_KEY+"&query=%s" %full_name
	print name_url
	response = urllib2.urlopen(name_url)
	data = json.load(response)
	actor_id = data['results'][0]['id']
	profile_url = None
	# Assign profile pic url if it exists
	if ('profile_path' in data['results'][0]):
		if data['results'][0]['profile_path']:
			profile_url = data['results'][0]['profile_path']
	# print actor_id
	query = 'movie?with_cast=%i' %(actor_id)
	url = base_url + 'discover/' + query + "&api_key=" + API_KEY
	# print url
	# Response for query for actors films will contain multiple pages.
	# Get first page to find num of pages
	response2 = urllib2.urlopen(url)
	pg1 = json.load(response2)
	num_pages = pg1['total_pages']
	movie_dict = get_movie_ids(pg1)
	#Now iterate over all remaining pages, adding movies to movie_dict dictionary
	temp = []

	for page in range(2,num_pages+1):
		#Get current page
		pagereq = '&page=%i' %page
		url = base_url + 'discover/' + query + pagereq + "&api_key=" + API_KEY
		current_pg = json.load(urllib2.urlopen(url))
		temp.append(current_pg)
		#Combine dict of movies from this page with previously found ones
		movie_dict += get_movie_ids(current_pg)

	# Remove repeated entries by movie_id and return
	# Note: turn this on if dealing with themoviedb bug on ordering searches

	movie_dict = remove_repeats(movie_dict)

	return movie_dict, actor_id, profile_url

# TODO: Way to refactor that reduces the number of movies we query for
# more detailed information?
# TODO: Replace this with a neural network!

def get_cast_pos(actor_id, movie_id, cast_id_min):
	"""Returns T/F for whether actor in top n of cast list"""
	query = base_url + 'movie/' + str(movie_id) + '/credits?' + "&api_key=" + API_KEY

	try:
		page = urllib2.urlopen(query)
	except urllib2.HTTPError, err:
		api_error = err.code
		page = None
	except urllib2.URLError, err:
		api_error = err.reason
		page = None

	if page:
		try:
			movie_cast = json.load(page)
		except ValueError:
			error = 'ValueError loading json'
			movie_cast = None


		if movie_cast:
			if movie_cast['cast']:
				castid = [act for act in movie_cast['cast'] if act['id']==actor_id][0]['order']
				# If no cast data then assume this movie isn't worth considering and force a False return
			else:
				# If no cast information then assume this movie isn't worth considering
				return False, None
			if (castid < cast_id_min):
				return True, None
			else:
				return False, None
		else:
			# Error decoding JSON, return None
			return None, error
	else:
		return None, api_error

# This has rest of logic for deciding on film
# TODO: Include error catching for these api calls too (put error catching into function)

def get_movie_score(movie_id):
	"""Checks whether movie passed satsifies criteria for being significant
	in actors career
	If actor in top n credits, returns revenue, average vote and popularity"""
	# Get movie info from api call
	# print movie_id
	query = base_url + 'movie/' + str(movie_id) +'?' + "&api_key=" + API_KEY
	score_json = json.load(urllib2.urlopen(query))

	# Get poularity ranking from themoviedb:
	if 'popularity' in score_json:
		pop = score_json['popularity']
	else:
		pop = 0
	# Get average vote the themoviedb:
	if 'vote_average' in score_json:
		vote = score_json['vote_average']
	else:
		vote = 0
	# Get revenue from themoviedb
	if 'revenue' in score_json:
		rev = score_json['revenue']
	else:
		rev = 0
	# Return values
	return {'revenue': rev, 'pop': pop, 'vote': vote}


def top_n_movies(full_name, actor_id, n, score_func):
	"""Returns movies ranked top n according to a score function,
	func(revenue, vote, popularity) that returns a float score from
	features"""
	# Pandas series for storing scores
	valid_movies = pd.Series(name='Score')
	valid_movies.index.name = 'Movie'
	# Get all movies for actor
	all_movies = get_movieapi_results(full_name)
	for name, movie_id in all_movies.items():
		check = get_movie_rank(actor_id, movie_id)
		if check:
			# If movie valid, pass data to score_func and store score
			valid_movies[name] = score_func(*check)






# TODO: Create route for index page
@application.route('/', methods=['GET'])
def index():
	return render_template('index.html')

@application.route('/test', methods=['GET'])
def test():
	return render_template('test.html')

@application.route('/return_list', methods=['GET'])
def return_list():
	return render_template('list.html')

@application.route('/get_d3_data/<name>/<sex>/<start_yr>', methods=['GET', 'POST'])
def get_d3_data(name, sex, start_yr):
	# Get raw name data from database
	data_list = model.get_name_data(name, sex, start_yr, 'python_dict')
	# Get total birth data to normalise
	totals = model.get_total_births(sex)

	# dict comprehension
	normed_dict = {yr:(data_list[yr]/float(totals[int(yr)])) for yr in data_list.keys()}

	# TODO: Note that this does not return a second error parameter,
	# which d3.json function expects normally (eg: see use of d3.json here:
	# http://www.brettdangerfield.com/post/realtime_data_tag_cloud/)
	return jsonify(**normed_dict)
	# return jsonify(**data_list)

@application.route('/get_movie_data/<f_name>/<l_name>', methods=['GET', 'POST'])
def get_movie_data(f_name, l_name):
	movie_dict, actor_id, profile_url = get_movieapi_results(f_name+" "+l_name)
	json = {'results': movie_dict, 'actor_id': actor_id, 'profile_url': profile_url}
	# print json['results']
	return jsonify(json)

# @application.route('/promise_test/<idstr>', methods=['GET', 'POST'])
# def promise_test(idstr):
# 	print "Promise route fired"
# 	# Wait a random time
# 	slp_time = int(math.floor(random.rand()*5))+1
# 	time.sleep(slp_time)
# 	modstr = 'oh my, '+idstr+', how nice'
# 	ret = bool(int(round(random.rand())))
# 	json = {'result': ret}
# 	return jsonify(json)

# TODO: Getting a 500 (internal server) error with 4110/963!!!!
# At very least, be prepared to deal with 500 in a way that can propogate
# TODO: Getting empty response with http://localhost:5000/cast_check/4110/165857
@application.route('/cast_check/<actor_id>/<movie_id>', methods=['GET', 'POST'])
def cast_check(actor_id, movie_id):
	# make cast_pos calls async with grequest if can't get promises
	# to work async with nginx etc...
	# TODO: Deal with 429 errors by addding to list and retrying at end
	# print movie_id
	cast_pos, error = get_cast_pos(int(actor_id), int(movie_id), 2)
	# Sleep to prevent 429 (TODO: Need a better solution for promises)
	time.sleep(0.2)
	json = {'result': cast_pos, 'error':error}
	return jsonify(json)


@application.route('/movie_score/<movie_id>', methods=['GET', 'POST'])
def movie_score(movie_id):
	outcome = get_movie_score(movie_id)
	outcome['movie_id'] = int(movie_id)
	time.sleep(0.2)
	return jsonify(outcome)

# TODO: Create route for getting data on user input
# Only need route for talking to my own backend
@application.route('/get_data', methods=["GET", "POST"])
def get_data():
	name = request.form['name']
	#Validate input
	name = check_str(name)
	data_list = model.get_name_data(name, 'F', 'python')
	return render_template('data_viz.html', data_list=data_list)


@application.route('/get_celeb_score', methods=["GET", "POST"])
def celeb_score_route():
	# Use get_json to return dict from json
	celeb_json = request.get_json(force=True)
	# Put births into dict
	births_dict = {year:births for year,births in celeb_json['baby_vals']}
	celeb_pval, score, hv, hb, perc = get_celeb_score(births_dict, celeb_json['celeb_yrs'])
	#Extract posted data from json
	return jsonify({'celeb_pval': celeb_pval, 'celeb_score': score, 'hist_vals':hv, 'hist_bins':hb, 'perc':perc})

if __name__ == '__main__':
	application.debug = True
	application.run()
	# application.run(host = '0.0.0.0')
