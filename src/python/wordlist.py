#!/usr/bin/env python3

import os
import sys
import traceback
import re
import glob
import argparse
import copy
import cltk
from kwic import *

from collections import OrderedDict
from collections import defaultdict
from lxml import etree
from cltk.corpus.utils.importer import CorpusImporter
from cltk.stem.lemma import LemmaReplacer
from cltk.stem.latin.j_v import JVReplacer
from nltk.corpus import stopwords
from cltk.tag.pos import POSTag
from cltk.stem.latin.stem import Stemmer
from repl import *
from wordlist_constants import *
from wordlist_output import *
from wordlist_strings import *
from wordlist_ngrams import *
from wordlist_classes import *
from wordlist_arguments import *
from wordlist_check_suspicious import *
from wordlist_commands import *
from wordlist_builder import *
from wordlist_getter import *

def print_usage():
	print("wordlist.py [file1] [file2] ... \n"
		   + "\t Create a list of words from the specified files")

def print_debug(string):
	if (DEBUG):
		print(string)

def flatten_list(word_list):
	flat_list = []
	for word in word_list:
		flat_list.append(word.text)
	return flat_list

def remove_digits(some_string):
	return ''.join([i for i in some_string if not i.isdigit()])

la_corpus_importer = CorpusImporter('latin')
la_corpus_importer.import_corpus('latin_text_latin_library')
la_corpus_importer.import_corpus('latin_models_cltk')
la_lemmatizer = LemmaReplacer('latin')
grc_corpus_importer = CorpusImporter('greek')
grc_corpus_importer.import_corpus('greek_models_cltk')
grc_lemmatizer = LemmaReplacer('greek')
def lemmatize(word_list, copy):
	for word in word_list:
		if copy:
			word.lemmatization = word.text
			return
		if word.language in LATIN_CODES:
			word.lemmatization = \
			    remove_digits(la_lemmatizer.lemmatize(word.text)[0])
		elif word.language in GREEK_CODES:
			word.lemmatization = \
			    remove_digits(grc_lemmatizer.lemmatize(word.text)[0])
		else:
			word.lemmatization = word.text

def print_word_info(word_string, word_dict):
	print("")
	language_dict = word_dict[word_string]
	for language in language_dict:
		word = language_dict[language]
		occurrences = language_dict[language].occurrences
		print("___" + language + "___")
		print("Occurances: " + str(len(occurrences)))
		print("Variations: ")
		for variation in word.variations:
			print("    " + variation)
		print("Files: ")
		for file_name in word.files:
			print("    " + file_name)
		print("Regions")
		for region in word.regions:
			print("    " + region)
		print("")

def get_words_from_file(path, file_dict, new_system):
	with open(path, "r") as path_file:
		file_string = path_file.read().replace("...", " ").encode("utf-8")
	root = etree.fromstring(file_string)
	words = []
	nsmap = {'tei': "http://www.tei-c.org/ns/1.0"}
	bodies = root.findall('.//' + TEI_NS + 'body')
	textLang = root.find('.//' + TEI_NS + 'textLang')
	textRegion = root.find('.//' + TEI_NS + 'region')
	if textRegion != None:
		file_dict[path] = iip_file(path, textRegion.text)	
	mainLang = ""
	if (textLang != None):
		mainLang = textLang.attrib['mainLang']
	for edition in (
		root.findall(".//tei:div[@type='edition']", namespaces=nsmap) 
		+ root.findall(".//tei:div[@type='translation']", 
		               namespaces=nsmap)
	):
		if mainLang.strip() == "":
			mainLang = "unk"
		edition_type = ""
		if 'subtype' in edition.attrib:
			edition_type = edition.attrib['subtype']
		if edition.attrib["type"] == "translation":
			edition_type = "translation"
			mainLang += "-transl"
		new_words = []
		if new_system:
			retrieved_words = get_words_from_element(edition)
			combined_words = ""
			for e in retrieved_words:
				combined_words += e.text + " "
			tagged_words = None
			if mainLang in LATIN_CODES:
				tagger = POSTag('latin')
				tagged_words = tagger.tag_crf(combined_words)
			elif mainLang in  GREEK_CODES:
				tagger = POSTag('greek')
				tagged_words = tagger.tag_crf(combined_words)
			if "-transl" in mainLang:
				tagged_words = nltk.pos_tag(nltk.word_tokenize(combined_words))
			for e in retrieved_words:
				new_words.append(iip_word_occurrence(
					edition_type,
					mainLang,
					e.text,
					path,
					textRegion.text,
					e.surrounding_elements
				))
				new_words[-1].internal_elements = e.internal_elements
				new_words[-1].alternatives = e.alternatives
				new_words[-1].preceding = e.preceding
				new_words[-1].following = e.following
				#if "transl" in mainLang:
				#	word_copy = copy(new_words[-1])
				#	word_copy.language = "transl"
				#	new_words.append(word_copy)
				if tagged_words != None:
					for tagged_word in tagged_words:
						if tagged_word[0] == e.text:
							new_words[-1].pos = tagged_word[1]
		else:
			new_words = [iip_word_occurrence(edition_type, 
			             mainLang, "", path, textRegion.text, [])]
			add_element_to_word_list(edition, new_words, edition, 
			                         mainLang, path, textRegion.text, 
			                         [])
		words += new_words
	
	null_words = []
	for word in words:
		word.text = str(word.text)
		for pattern in IGNORE:
			word.text = word.text.replace(pattern, "")
		if (word.text.strip() == ""):
			null_words.append(word)	
		if word.language.strip() == "":
			word.language = "unk"
	words = [x for x in words if x not in null_words]
	return words

if __name__ == '__main__':
	parser = argparse.ArgumentParser(description="""Produce word list 
	                                                from files.""")
	args = add_arguments(parser).parse_args()
	new_system = True
	if args.old_system:
		new_system = False

	# Extract words from each file
	occurrences = []  # Contains the iip_word_occurrence objects 
	# Contains the iip_word objects
	word_dict = defaultdict(lambda: defaultdict(lambda: iip_word()))
	file_dict = {} # Maps file names to iip_file objects
	languages = set()
	
	plaintextdir = "flat"
	plaintext_lemmatize = True
	if args.nolemma != None:
		plaintext_lemmatize = not args.nolemma
	if args.flat != None:
		plaintextdir = args.flat
	for file in args.files:
		try:
			new_words = get_words_from_file(file, file_dict, new_system)
			lemmatize(new_words, args.nolemma)
			add_kwic_to_occurrences(new_words)
			if args.plaintext:
				occurrence_list_to_plain_text(new_words, plaintextdir
				                              + "_lemma/" + file.split("/")[-1]
				                              .replace(".xml", ""))
				occurrence_list_to_plain_text(new_words, plaintextdir
				                              + "/" + file.split("/")[-1]
				                              .replace(".xml", ""), False)
			occurrences += new_words
		except Exception as exception:
			if args.fileexception:
				raise exception
			else:
				sys.stderr.write("Cannot read " + file + "\n")

	# If this is too slow, it should be changed to be parameters for 
	# get_words_from_file so as to avoid iterating over the entire 
	# list.		
	filtered_words = []
	stop_words = set(stopwords.words('english'))
	for word in occurrences:
		languages.add(word.language)
		# Filter the word ocurances if necessary
		add = True
		if args.nodiplomatic:
			if word.edition_type == "diplomatic":
				add = False
		if args.engstops:
			if (word.text in stop_words and 
			          "transl" in word.language):
				add = False
		if add:
			filtered_words.append(word)
		
		word.xml_context = ""
		
		delayed_prepend = []
		delayed_postpend =[]
		for i in range(0, len(word.text)):
			for e in word.internal_elements:
				if not isinstance(e.tag, str):
					continue
				if (word.internal_elements[e].start_index == i 
				and word.internal_elements[e].end_index == i):
					word.xml_context += "<" + e.tag + "/>"
				else:
					if word.internal_elements[e].start_index == i:
						word.xml_context += "<" + e.tag + ">"
						delayed_postpend.append(e)
					if word.internal_elements[e].end_index == i:
						word.xml_context += "</" + e.tag + ">"
						if e in delayed_postpend:
							delayed_postpend.remove(e)
						else:
							delayed_prepend.append(e)
			word.xml_context += word.text[i]
		for e in delayed_prepend:
			word.xml_context = "<" + e.tag + ">" + word.xml_context
		for e in delayed_postpend:
			word.xml_context = word.xml_context + "</"+ e.tag + ">"
		
		for e in reversed(word.within):
			if not isinstance(e.tag, str):
				continue
			tag = e.tag.split("}")[1]
			if tag == "div":
				continue
			start_tag = "<" + tag
			for attribute in e.attrib:
				start_tag += " " + attribute + "="
				start_tag += '"' + e.attrib[attribute] + '"'
			start_tag += ">"
			word.xml_context = (start_tag + word.xml_context 
			                    + "</" + tag + ">")
			
		word.xml_context = word.xml_context.replace(XML_NS, "")\
			.replace(TEI_NS,"")
		
	if args.nodiplomatic or args.engstops:
		occurrences = filtered_words

	lang_count = defaultdict(lambda: 0)

	for word in occurrences:
		lang_count[word.language] += 1
		
		# Add occurrences to dictionary
		word_languages = [word.language]
		if "transl" in word.language:
			word_languages.append("transl")
			languages.add("transl")
		for language in word_languages:
			word_dict[word.lemmatization.lower()][language]\
				.occurrences.append(word)
			word_dict[word.lemmatization.lower()][language]\
				.variations.add(word.text.lower())
			word_dict[word.lemmatization.lower()][language]\
				.files.add(word.file_name)
			word_dict[word.lemmatization.lower()][language]\
				.language = word.language
			word_dict[word.lemmatization.lower()][language]\
				.lemma = word.lemmatization
			word_dict[word.lemmatization.lower()][language]\
				.regions.add(file_dict[word.file_name].region)
	
		check_suspicious(
			word_dict[word.lemmatization.lower()][word.language]
		)

	la_stemmer = Stemmer()
	for key in word_dict:
		for language in word_dict[key]:
			word = word_dict[key][language]
			word.frequency_total = \
				len(word.occurrences) / len(occurrences)
			word.frequency_language = \
				len(word.occurrences) / lang_count[word.language]
			if language == "la":
				word.stem = la_stemmer.stem(word.lemma)

	# Sort according to the given arguments before writing to file
	sort_order = []
	if args.sort != None:
		for e in args.sort:
			if e == 'l':
				sort_order.append("language")
			elif e == 't' or e == 'a':
				sort_order.append("text")
			elif e == 'f':
				sort_order.append("file_name")
			elif e == "e":
				sort_order.append("edition_type")
			else:
				print("Invalid sort criterion: '" + e + "'")
	sort_order.reverse()
	for field in sort_order:
		occurrences = sorted(occurrences, key=lambda word: 
			                        word.__dict__[field])
	# Print each extracted word on a new line
	if not args.silent:
		for word in occurrences:		
			word.print()

	# Output words to files
	output_name = DEFAULT_OUTPUT_NAME;
	if args.name != None:
		output_name = args.name
	if args.html:
		occurrence_list_to_html(occurrences, langfiles=args.langfiles)
	if args.csv:
		occurrence_list_to_csv(occurrences, langfiles=args.langfiles)
	if args.html_general:
		word_list_to_html(word_dict, languages, output_name=".")
	if args.repl:
		main_repl = repl_instance()
		main_repl.add_repl_command(word_info_command(word_dict))
		main_repl.run_repl()
	sys.exit(0)
